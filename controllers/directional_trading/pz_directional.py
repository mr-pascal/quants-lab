from decimal import Decimal
from typing import List

import pandas_ta as ta  # noqa: F401
from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.core.data_type.common import TradeType, OrderType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig, TripleBarrierConfig, \
    TrailingStop
from hummingbot.strategy_v2.models.executor_actions import ExecutorAction, StopExecutorAction
from pydantic import Field, validator

from core.features.candles.peak_analyzer import PeakAnalyzer
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo


""""
Long Condition:

close > HMA(10)
Close > HMA(20)
HMA(10) > HMA(20)

RSI_MA = Green
SRSI = Green

---
? Crossover as entry ?
? Higher TImeframe Filter (HMA/EMA) ?
? HMA(50) oder EMA(50) als trendfilter?


"""


class PZDirectionalControllerConfig(DirectionalTradingControllerConfigBase):
    controller_name = "pz_directional"
    candles_config: List[CandlesConfig] = []
    candles_connector: str = Field(
        default=None)
    candles_trading_pair: str = Field(
        default=None)
    interval: str = Field(
        default="3m",
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the candle interval (e.g., 1m, 5m, 1h, 1d): ",
            prompt_on_new=False))
    
    # Indicator inputs
    ema_medium: int = 20
    ema_slow: int = 50
    hma_fast: int = 10
    hma_slow: int = 20
    srsi_length:int = 9
    srsi_smoothing: int = 3
    rsi_ma_length: int = 9
    natr_length: int = 14

    # Factor inputs
    sl_natr_factor: Decimal = 3.0
    ts_activation_natr_factor: Decimal = 1
    ts_delta_natr_factor: Decimal = 0.5


    @validator("candles_connector", pre=True, always=True)
    def set_candles_connector(cls, v, values):
        if v is None or v == "":
            return values.get("connector_name")
        return v

    @validator("candles_trading_pair", pre=True, always=True)
    def set_candles_trading_pair(cls, v, values):
        if v is None or v == "":
            return values.get("trading_pair")
        return v


class PZDirectionalController(DirectionalTradingControllerBase):

    def __init__(self, config: PZDirectionalControllerConfig, *args, **kwargs):
        self.config = config
        self.max_records = max(
            # config.ema_short, 
            # config.ema_medium, 
            config.hma_fast,
            config.hma_slow,
            config.ema_slow
            ) + 20
        if len(self.config.candles_config) == 0:
            self.config.candles_config = [CandlesConfig(
                connector=config.candles_connector,
                trading_pair=config.candles_trading_pair,
                interval=config.interval,
                max_records=self.max_records
            )]
        super().__init__(config, *args, **kwargs)

    async def update_processed_data(self):
        df = self.market_data_provider.get_candles_df(connector_name=self.config.candles_connector,
                                                      trading_pair=self.config.candles_trading_pair,
                                                      interval=self.config.interval,
                                                      max_records=self.max_records)
        
        close = df["close"]
        
        # Add indicators
        # df.ta.ema(length=self.config.ema_short, append=True)
        df.ta.ema(length=self.config.ema_medium, append=True)
        df.ta.ema(length=self.config.ema_slow, append=True)
        df.ta.hma(length=self.config.hma_fast, append=True)
        df.ta.hma(length=self.config.hma_slow, append=True)
       
        df.ta.natr(length=self.config.natr_length, append=True)

        df.ta.stochrsi(close=close, length=self.config.srsi_length, rsi_length=self.config.srsi_length, k=self.config.srsi_smoothing, d=self.config.srsi_smoothing, mamode="sma", append=True)


        df.ta.rsi(close=close, length=self.config.rsi_ma_length, append=True)
        df.ta.wma(close=df[f"RSI_{self.config.rsi_ma_length}"], length=self.config.rsi_ma_length, append=True)

        # short_ema = df[f"EMA_{self.config.ema_short}"]
        # ema_medium = df[f"EMA_{self.config.ema_medium}"]
        ema_slow = df[f"EMA_{self.config.ema_slow}"]
        hma_fast = df[f"HMA_{self.config.hma_fast}"]
        hma_slow = df[f"HMA_{self.config.hma_slow}"]

        # Add shifts
        df[f"HMA_{self.config.hma_fast}_1"] = hma_fast.shift(1)
        df[f"HMA_{self.config.hma_slow}_1"] = hma_slow.shift(1)
        df["close_1"] = df["close"].shift(1)


        k = df[f"STOCHRSIk_{self.config.srsi_length}_{self.config.srsi_length}_{self.config.srsi_smoothing}_{self.config.srsi_smoothing}"]
        d = df[f"STOCHRSId_{self.config.srsi_length}_{self.config.srsi_length}_{self.config.srsi_smoothing}_{self.config.srsi_smoothing}"]

        rsi = df[f"RSI_{self.config.rsi_ma_length}"]
        rsi_ma = df[f"WMA_{self.config.rsi_ma_length}"]


        long_condition = (close > hma_fast) & (hma_fast > hma_slow)  & (rsi > rsi_ma) & (close > ema_slow)
        short_condition = (close < hma_fast) & (hma_fast < hma_slow)  & (rsi < rsi_ma) & (close < ema_slow)

        # Important: Add crossover, otherwise too many positions at bad timing
        bullish_hma_crossover = (hma_fast > hma_slow) & (hma_fast.shift(1) <= hma_slow.shift(1))
        bearish_hma_crossover = (hma_fast < hma_slow) & (hma_fast.shift(1) >= hma_slow.shift(1))

        long_condition = long_condition & bullish_hma_crossover
        short_condition = short_condition & bearish_hma_crossover

        # TODO: Add check for oversold/overbought in RSI and SRSI


        df["signal"] = 0
        df.loc[long_condition, "signal"] = 1
        df.loc[short_condition, "signal"] = -1

        self.processed_data.update(df.iloc[-1].to_dict())
        self.processed_data["features"] = df

    def get_executor_config(self, trade_type: TradeType, price: Decimal, amount: Decimal):
        """
        Get the executor config based on the trade_type, price and amount. This method can be overridden by the
        subclasses if required.
        """

        natr = Decimal(self.processed_data[f"NATR_{self.config.natr_length}"]) / Decimal(100.0)

        # SL = Factor * NATR
        self.config.stop_loss = self.config.sl_natr_factor * natr
        # print(self.config.stop_loss)
        # print(self.config.triple_barrier_config)

        self.config.trailing_stop=TrailingStop(
            activation_price=Decimal(self.config.ts_activation_natr_factor * natr), 
            trailing_delta=Decimal(self.config.ts_delta_natr_factor * natr)
        )

        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            side=trade_type,
            entry_price=price,
            amount=amount,
            triple_barrier_config=self.config.triple_barrier_config,
            leverage=self.config.leverage,
        )
    
    def get_all_executors(self) -> List[ExecutorInfo]:
        return self.executors_info
        # return [executor for executors in self.executors_info.values() for executor in executors]
    
    def get_active_executors_by_side(self, connector_name: str, trading_pair: str):
        active_executors_by_connector_pair = self.filter_executors(
            executors=self.get_all_executors(),
            filter_func=lambda e: e.connector_name == connector_name and e.trading_pair == trading_pair and e.is_active
        )
        active_longs = [e for e in active_executors_by_connector_pair if e.side == TradeType.BUY]
        active_shorts = [e for e in active_executors_by_connector_pair if e.side == TradeType.SELL]
        return active_longs, active_shorts
    
    def stop_actions_proposal(self) -> List[StopExecutorAction]:
        stop_actions = []

        # print(self.executors_info)

        ema_medium = self.processed_data[f"EMA_{self.config.ema_medium}"]

        hma_fast = self.processed_data[f"HMA_{self.config.hma_fast}"]
        hma_fast_1 = self.processed_data[f"HMA_{self.config.hma_fast}_1"]
                
        hma_slow = self.processed_data[f"HMA_{self.config.hma_slow}"]
        hma_slow_1 = self.processed_data[f"HMA_{self.config.hma_slow}_1"]

        # Kinda like a stop at the EMA/HMA one, whatever is bigger
        bigger = max(ema_medium, hma_slow)
        smaller = max(ema_medium, hma_slow)

        close = self.processed_data["close"]
        close_1 = self.processed_data["close_1"]

        bearish_close_hma_crossover = (close < smaller) & (close_1 > smaller)
        bullish_close_hma_crossover = (close > bigger) & (close_1 < bigger)
        
        # bullish_crossover = (hma_fast > hma_slow) & (hma_fast_1 < hma_slow_1)
        # bearish_crossover = (hma_fast < hma_slow) & (hma_fast_1 > hma_slow_1)

        long_exit_signal =  bearish_close_hma_crossover
        short_exit_signal = bullish_close_hma_crossover
        
        active_longs, active_shorts = self.get_active_executors_by_side(self.config.connector_name,
                                                                        self.config.trading_pair)
        
        if len(active_longs) > 0 and long_exit_signal:
            stop_actions.extend([StopExecutorAction(executor_id=e.id) for e in active_longs])
        if len(active_shorts) > 0 and short_exit_signal:
            stop_actions.extend([StopExecutorAction(executor_id=e.id) for e in active_shorts])

        return stop_actions