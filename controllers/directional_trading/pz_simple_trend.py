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


class PZSimpleDirectionalControllerConfig(DirectionalTradingControllerConfigBase):
    controller_name = "pz_simple_trend"
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
    ema_fast: int = 10
    ema_medium: int = 20
    ema_slow: int = 50
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


class PZSimpleDirectionalController(DirectionalTradingControllerBase):

    def __init__(self, config: PZSimpleDirectionalControllerConfig, *args, **kwargs):
        self.config = config
        self.max_records = max(
            config.ema_fast,
            config.ema_medium,
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
        df.ta.ema(length=self.config.ema_fast, append=True)
        df.ta.ema(length=self.config.ema_medium, append=True)
        df.ta.ema(length=self.config.ema_slow, append=True)
        df.ta.natr(length=self.config.natr_length, append=True)

        ema_fast = df[f"EMA_{self.config.ema_fast}"]
        ema_medium = df[f"EMA_{self.config.ema_medium}"]
        ema_slow = df[f"EMA_{self.config.ema_slow}"]

        # Add shifts
        df[f"EMA_{self.config.ema_fast}_1"] = ema_fast.shift(1)
        df[f"EMA_{self.config.ema_medium}_1"] = ema_medium.shift(1)
        df[f"EMA_{self.config.ema_slow}_1"] = ema_slow.shift(1)

        df["close_1"] = df["close"].shift(1)



        # TODO: + add EMA_slow slope?
        long_condition = (close > ema_fast) & (ema_fast > ema_medium) #& (close > ema_slow)
        short_condition = (close < ema_fast) & (ema_fast < ema_medium) #& (close < ema_slow)


        # Important: Add crossover, otherwise too many positions at bad timing
        bullish_crossover = (ema_fast > ema_medium) & (ema_fast.shift(1) < ema_medium.shift(1))
        bearish_crossover = (ema_fast < ema_medium) & (ema_fast.shift(1) > ema_medium.shift(1))

        # volatility = df[f"NATR_{self.config.natr_length}"]
        # trend_filter = volatility > volatility.rolling(20).mean()

        # TODO: add maybe smth like ADX or so?


        long_condition = long_condition & bullish_crossover
        short_condition = short_condition & bearish_crossover

        

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
        # self.config.stop_loss = self.config.sl_natr_factor * natr

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
        ema_fast = self.processed_data[f"EMA_{self.config.ema_fast}"]
        ema_medium = self.processed_data[f"EMA_{self.config.ema_medium}"]
        ema_medium_1 = self.processed_data[f"EMA_{self.config.ema_medium}_1"]
        ema_slow = self.processed_data[f"EMA_{self.config.ema_slow}"]
        ema_slow_1 = self.processed_data[f"EMA_{self.config.ema_slow}_1"]


        close = self.processed_data["close"]
        close_1 = self.processed_data["close_1"]

        bearish_close_hma_crossover = (close < ema_medium) & (close_1 > ema_medium_1)
        bullish_close_hma_crossover = (close > ema_medium) & (close_1 < ema_medium_1)

        close_over_ema = close_1 > ema_slow_1
        close_under_ema = close_1 < ema_slow_1

        long_exit_signal = close_under_ema # bearish_close_hma_crossover
        short_exit_signal = close_over_ema # bullish_close_hma_crossover
        
        active_longs, active_shorts = self.get_active_executors_by_side(self.config.connector_name,
                                                                        self.config.trading_pair)
        
        if len(active_longs) > 0 and long_exit_signal:
            stop_actions.extend([StopExecutorAction(executor_id=e.id) for e in active_longs])
        if len(active_shorts) > 0 and short_exit_signal:
            stop_actions.extend([StopExecutorAction(executor_id=e.id) for e in active_shorts])

        return stop_actions