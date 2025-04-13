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
# from hummingbot.strategy_v2.models.executor_actions import ExecutorAction, StopExecutorAction
from pydantic import Field, validator

# from core.features.candles.peak_analyzer import PeakAnalyzer
# from hummingbot.strategy_v2.models.executors_info import ExecutorInfo

class PZScalperControllerConfig(DirectionalTradingControllerConfigBase):
    controller_name = "pz_scalper"
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
    ema_fast: int = 50
    ema_slow: int = 100
    srsi_smoothing: int = 3
    srsi_length: int = 9
    rsi_ma_length: int  = 9
    hma_fast: int = 20
    hma_slow : int = 50
    hma_diff_ma_length: int = 9
    natr_length: int = 14

    # Factor inputs
    tp_natr_factor: Decimal = 1.0
    sl_natr_factor: Decimal = 3.0

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


class PZScalperController(DirectionalTradingControllerBase):

    def __init__(self, config: PZScalperControllerConfig, *args, **kwargs):
        self.config = config
        self.max_records = max(
            config.hma_fast,
            config.hma_slow,
            config.natr_length,
            config.ema_slow,
            config.ema_fast,
            config.srsi_length,
            config.srsi_smoothing,
            config.rsi_ma_length,
            config.hma_diff_ma_length
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
        
        df = df.copy()
        close = df["close"]
        
        # Add indicators to Dataframe
        df.ta.ema(length=self.config.ema_fast, append=True)
        df.ta.ema(length=self.config.ema_slow, append=True)
        df.ta.hma(length=self.config.hma_fast, append=True)
        df.ta.hma(length=self.config.hma_slow, append=True)
        df.ta.natr(length=self.config.natr_length, append=True)
        df.ta.stochrsi(close=close, length=self.config.srsi_length, rsi_length=self.config.srsi_length, k=self.config.srsi_smoothing, d=self.config.srsi_smoothing, mamode="sma", append=True)
        df.ta.rsi(close=close, length=self.config.rsi_ma_length, append=True)
        df.ta.wma(close=df[f"RSI_{self.config.rsi_ma_length}"], length=self.config.rsi_ma_length, append=True)
        df[f"HMA_DIFF"] = df["close"] - df[f"HMA_{self.config.hma_fast}"] - df[f"HMA_{self.config.hma_slow}"]
        df.ta.ema(close=df[f"HMA_DIFF"], length= self.config.hma_diff_ma_length, append=True)

        # Get Dataframe values
        rsi = df[f"RSI_{self.config.rsi_ma_length}"]
        rsi_ma = df[f"WMA_{self.config.rsi_ma_length}"]
        k = df[f"STOCHRSIk_{self.config.srsi_length}_{self.config.srsi_length}_{self.config.srsi_smoothing}_{self.config.srsi_smoothing}"]
        d = df[f"STOCHRSId_{self.config.srsi_length}_{self.config.srsi_length}_{self.config.srsi_smoothing}_{self.config.srsi_smoothing}"]
        ema_fast = df[f"EMA_{self.config.ema_fast}"]
        ema_slow = df[f"EMA_{self.config.ema_slow}"]
        hma_fast = df[f"HMA_{self.config.hma_fast}"]
        hma_slow = df[f"HMA_{self.config.hma_slow}"]
        hma_diff = df[f"HMA_DIFF"]
        hma_diff_ema = df[f"EMA_{self.config.hma_diff_ma_length}"]

        # Long condition
        hma_diff_over_hma_diff_ema = hma_diff > hma_diff_ema
        srsi_green = k > d
        srsi_not_overbought = d < 50
        rsi_ma_green = rsi > rsi_ma
        close_over_emas = (close > ema_fast) & (ema_fast > ema_slow)
        hma_bullish_crossover = (hma_fast > hma_slow) & (hma_fast.shift(1) < hma_slow.shift(1))
        long_condition = hma_diff_over_hma_diff_ema & srsi_green & srsi_not_overbought & rsi_ma_green  & close_over_emas & hma_bullish_crossover
        

        # Short Condition
        hma_diff_below_hma_diff_ema = hma_diff < hma_diff_ema
        srsi_red = k < d
        srsi_not_oversold = d > 50
        rsi_ma_red = rsi < rsi_ma
        close_below_emas = (close < ema_fast) & (ema_fast < ema_slow)
        hma_bearish_crossover = (hma_fast < hma_slow) & (hma_fast.shift(1) > hma_slow.shift(1))
        short_condition = hma_diff_below_hma_diff_ema & srsi_red & srsi_not_oversold & rsi_ma_red  & close_below_emas & hma_bearish_crossover

        df.loc[:, "signal"] = 0
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
        # TP = Factor * NATR
        self.config.take_profit = self.config.tp_natr_factor * natr

        self.config.trailing_stop= None

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