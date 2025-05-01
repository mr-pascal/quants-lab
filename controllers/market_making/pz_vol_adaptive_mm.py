from decimal import Decimal
from typing import List, Tuple

import pandas as pd
import pandas_ta as ta
from pydantic import Field, validator

from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.core.data_type.common import TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
    MarketMakingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import (
    PositionExecutorConfig, TrailingStop
)


class VolAdaptiveMMConfig(MarketMakingControllerConfigBase):
    controller_name = "vol_adaptive_mm"

    # Candle feed config
    candles_config: List[CandlesConfig] = []
    candles_connector: str = Field(default=None)
    candles_trading_pair: str = Field(default=None)
    interval: str = "1m"

    # Indicator configs
    hma_fast: int = 10
    hma_slow: int = 20
    hma_diff_ma: int = 9
    stoch_rsi_smoothing: int = 3
    stoch_rsi_length: int = 9
    natr_length: int = 14

    # Spread and fee buffer
    taker_fee: float = 0.00055
    maker_fee: float = 0.0002
    buffer: float = 0.0001 # 0.0005

    @property
    def total_fees(self) -> float:
        return self.taker_fee + self.maker_fee

    @property
    def minimum_spread_per_side(self) -> float:
        return (self.total_fees + self.buffer) / 2

    @validator("candles_connector", pre=True, always=True)
    def set_default_connector(cls, v, values):
        return v or values.get("connector_name")

    @validator("candles_trading_pair", pre=True, always=True)
    def set_default_trading_pair(cls, v, values):
        return v or values.get("trading_pair")


class VolAdaptiveMMController(MarketMakingControllerBase):
    """
    A volatility-adaptive market making strategy with trend detection, spread skewing,
    and delta-neutral behavior designed for low-latency futures trading.
    """

    def __init__(self, config: VolAdaptiveMMConfig, *args, **kwargs):
        self.config = config
        self.max_records = max(config.hma_fast, config.hma_slow, config.hma_diff_ma, config.natr_length) + 100
        if not config.candles_config:
            config.candles_config = [
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval,
                    max_records=self.max_records
                )
            ]
        super().__init__(config, *args, **kwargs)

    async def update_processed_data(self):
        """Fetches candle data and computes indicators to produce adjusted midprice and spread multipliers."""
        candles = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval,
            max_records=self.max_records
        )

        # NATR-based volatility
        natr = ta.natr(candles["high"], candles["low"], candles["close"], length=self.config.natr_length) / 100

        # Hull Moving Averages
        hma_fast = ta.hma(candles["close"], length=self.config.hma_fast)
        hma_slow = ta.hma(candles["close"], length=self.config.hma_slow)
        hma_diff = ((candles["close"] - hma_fast) + (candles["close"] - hma_slow)) / candles["close"] * 100
        hma_diff_ema = ta.ema(hma_diff, length=self.config.hma_diff_ma)
        trend_signal = (hma_diff_ema > 0).astype(int) * 2 - 1  # +1 or -1

        # StochRSI-based overbought/oversold detection
        srsi = ta.stochrsi(candles["close"], length=self.config.stoch_rsi_length,
                           rsi_length=self.config.stoch_rsi_length,
                           k=self.config.stoch_rsi_smoothing, d=self.config.stoch_rsi_smoothing)
        k_col = srsi.columns[0]
        d_col = srsi.columns[1]
        srsi_signal = srsi[d_col].apply(lambda x: -1 if x > 80 else (1 if x < 20 else 0))

        # Combine trend and momentum signals
        signal_multiplier = (trend_signal + srsi_signal) / 2
        signal_multiplier = 1.0
        price_adjustment = signal_multiplier * natr * 0.8

        price_multiplier = price_adjustment.iloc[-1]
        reference_price = candles["close"] * (1 + price_multiplier)

        print(f"[DEBUG] Last close price: {candles['close'].iloc[-1]:.6f}")
        print(f"[DEBUG] NATR (volatility): {(natr.iloc[-1] * 100):.4f}%")
        print(f"[DEBUG] Trend signal: {trend_signal.iloc[-1]}")
        print(f"[DEBUG] StochRSI signal: {srsi_signal.iloc[-1]}")
        # print(f"[DEBUG] Signal Multiplier: {signal_multiplier.iloc[-1]}")
        print(f"[DEBUG] Price Multiplier (%): {(price_multiplier * 100):.4f}%")
        print(f"[DEBUG] Reference price: {reference_price.iloc[-1]:.6f}")


        candles = candles.copy()

        candles["spread_multiplier"] = natr
        candles["reference_price"] = reference_price
        candles["trend_signal"] = trend_signal
        
        # candles["close"] # reference_price_value
        # candles["price_multiplier"] = price_multiplier
        # candles["signal_multiplier"] = signal_multiplier

        self.processed_data = {
            # Necessary for the MM Algo
            "reference_price": Decimal(candles["reference_price"].iloc[-1]),
            "spread_multiplier": Decimal(candles["spread_multiplier"].iloc[-1]),
            "features": candles,


            ### CUSTOM DATA
            # FIXME: replace with "singla multiplier"?
            "trend_signal": candles["trend_signal"].iloc[-1],

        }

    # def get_price_and_amount(self, level_id: str) -> Tuple[Decimal, Decimal]:

    #     trade_type = self.get_trade_type_from_level_id(level_id)
    #     level = self.get_level_from_level_id(level_id)
    #     spreads, amounts_quote = self.config.get_spreads_and_amounts_in_quote(trade_type)


    #     base_spread = Decimal(spreads[int(level)]) * Decimal(self.processed_data["spread_multiplier"])
    #     # Ensure floor via NATR or fee buffer
    #     vol_floor = Decimal("0.5") * Decimal(self.processed_data["spread_multiplier"])
    #     min_spread = Decimal(self.config.minimum_spread_per_side)
    #     effective_spread = max(base_spread, vol_floor, min_spread)

    #     skew = Decimal("0.2") * Decimal(self.processed_data["trend_signal"]) * effective_spread
    #     direction = Decimal("-1") if trade_type == TradeType.BUY else Decimal("1")
    #     order_price = Decimal(self.processed_data["reference_price"]) * Decimal(1 + direction * (effective_spread + skew))
    #     order_amount = Decimal(amounts_quote[int(level)]) / order_price

    #     print("[DEBUG] --- ORDER DETAILS ---")
    #     print(f"Trade Type: {trade_type.name}")
    #     print(f"Level: {level}")
    #     print(f"Spread Multiplier (NATR): {self.processed_data['spread_multiplier']:.6f}")
    #     print(f"Base Spread: {base_spread:.6f}")
    #     print(f"Vol Floor: {vol_floor:.6f}")
    #     print(f"Min Spread: {min_spread:.6f}")
    #     print(f"Effective Spread: {effective_spread:.6f}")
    #     print(f"Skew: {skew:.6f}")
    #     print(f"Final Order Price: {order_price:.4f}")
    #     print(f"Reference Price: {self.processed_data['reference_price']:.4f}")
    #     print(f"Quote Amount (target): {amounts_quote[int(level)]:.4f}")
    #     print(f"Base Amount (order): {order_amount:.6f}")
    #     print("--------------------------")

    #     return order_price, order_amount

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal) -> PositionExecutorConfig:
        trade_type = self.get_trade_type_from_level_id(level_id)
        natr = Decimal(self.processed_data["spread_multiplier"])
        self.config.take_profit = Decimal(self.config.minimum_spread_per_side)
        self.config.stop_loss = Decimal("0.5") * natr
        self.config.trailing_stop = None

        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=amount,
            triple_barrier_config=self.config.triple_barrier_config,
            leverage=self.config.leverage,
            side=trade_type,
        )
    # def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
    #     trade_type = self.get_trade_type_from_level_id(level_id)
    #     return PositionExecutorConfig(
    #         timestamp=self.market_data_provider.time(),
    #         level_id=level_id,
    #         connector_name=self.config.connector_name,
    #         trading_pair=self.config.trading_pair,
    #         entry_price=price,
    #         amount=amount,
    #         triple_barrier_config=self.config.triple_barrier_config,
    #         leverage=self.config.leverage,
    #         side=trade_type,
    #     )
