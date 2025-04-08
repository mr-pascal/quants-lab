from decimal import Decimal
from typing import List, Tuple

import pandas_ta as ta  # noqa: F401
from pydantic import Field, validator
import pandas as pd
from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
    MarketMakingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import (
    PositionExecutorConfig, TrailingStop
)
from hummingbot.core.data_type.common import TradeType

class PZMMControllerConfig(MarketMakingControllerConfigBase):
    controller_name = "pz_mm"
    candles_config: List[CandlesConfig] = []
    buy_spreads: List[float] = Field(
        default="1,2,4",
        client_data=ClientFieldData(
            is_updatable=True,
            prompt_on_new=True,
            prompt=lambda mi: "Enter a comma-separated list of buy spreads (e.g., '0.01, 0.02'):",
        ),
    )
    sell_spreads: List[float] = Field(
        default="1,2,4",
        client_data=ClientFieldData(
            is_updatable=True,
            prompt_on_new=True,
            prompt=lambda mi: "Enter a comma-separated list of sell spreads (e.g., '0.01, 0.02'):",
        ),
    )
    candles_connector: str = Field(
        default=None,
        client_data=ClientFieldData(
            prompt_on_new=True,
            prompt=lambda mi: "Enter the connector for the candles data, leave empty to use the same exchange as the connector: ",
        ),
    )
    candles_trading_pair: str = Field(
        default=None,
        client_data=ClientFieldData(
            prompt_on_new=True,
            prompt=lambda mi: "Enter the trading pair for the candles data, leave empty to use the same trading pair as the connector: ",
        ),
    )
    interval: str = "1m"

    # NOTE: Those properties inherited!
    # buy_amounts_pct: List[Decimal] = [0.01]
    # sell_amounts_pct: List[Decimal] = [0.01]

    hma_very_slow: int = 50
    hma_slow: int = 20
    hma_fast: int = 10
    rsi_length: int = 9
    stoch_rsi_smoothing: int = 3
    stoch_rsi_length: int = 9
    natr_length: int = 14
    tp_natr_factor: Decimal = 0.5
    sl_natr_factor: Decimal = 0.5
    ts_activation_natr_factor: Decimal = 0.1 
    ts_delta_natr_factor: Decimal = 0.02



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


class PZMMController(MarketMakingControllerBase):
    """
    This is a pz version of the PMM controller.It uses the MACD to shift the mid-price and the NATR
    to make the spreads pz. It also uses the Triple Barrier Strategy to manage the risk.
    """

    def __init__(self, config: PZMMControllerConfig, *args, **kwargs):
        import sys
        sys.stdout.write("debug info\n")
        sys.stdout.flush()
        self.config = config
        self.max_records = (
            max(
                config.hma_very_slow,
                config.hma_slow,
                config.hma_fast,
                config.rsi_length,
                config.natr_length,
            )
            + 100
        )
        if len(self.config.candles_config) == 0:
            self.config.candles_config = [
                CandlesConfig(
                    connector=config.candles_connector,
                    trading_pair=config.candles_trading_pair,
                    interval=config.interval,
                    max_records=self.max_records,
                )
            ]
        super().__init__(config, *args, **kwargs)

    def get_price_multiplier(
        self,
        candles: pd.DataFrame,
        natr_length: int,
        rsi_length: int,
        stoch_rsi_length: int,
        stoch_rsi_smoothing: int,
        hma_very_slow: int,
        hma_slow: int,
        hma_fast: int,
    ) -> tuple[pd.Series, pd.Series]:
        natr = (
            ta.natr(
                candles["high"],
                candles["low"],
                candles["close"],
                length=natr_length,
            )
            / 100
        )
        rsi = ta.rsi(candles["close"], length=rsi_length)
        rsi_wma = ta.wma(rsi, length=rsi_length)

        stochrsi = ta.stochrsi(
            candles["close"],
            length=stoch_rsi_length,
            rsi_length=stoch_rsi_length,
            k=stoch_rsi_smoothing,
            d=stoch_rsi_smoothing,
            mamode="sma",
            append=False,
        )

        k = stochrsi[
            f"STOCHRSIk_{stoch_rsi_length}_{stoch_rsi_length}_{stoch_rsi_smoothing}_{stoch_rsi_smoothing}"
        ]
        d = stochrsi[
            f"STOCHRSId_{stoch_rsi_length}_{stoch_rsi_length}_{stoch_rsi_smoothing}_{stoch_rsi_smoothing}"
        ]

        hma_very_slow_output = ta.hma(
            candles["close"],
            length=hma_very_slow,
            offset=0,
        )
        hma_slow_output = ta.hma(
            candles["close"],
            length=hma_slow,
            offset=0,
        )
        hma_fast_output = ta.hma(
            candles["close"],
            length=hma_fast,
            offset=0,
        )
        hma_very_slow_signal = candles["close"] - hma_very_slow_output
        hma_very_slow_signal = hma_very_slow_signal.apply(
            lambda x: 1 if x > 0 else -1
        )
        hma_slow_signal = candles["close"] - hma_slow_output
        hma_slow_signal = hma_slow_signal.apply(lambda x: 1 if x > 0 else -1)
        hma_fast_signal = candles["close"] - hma_fast_output
        hma_fast_signal = hma_fast_signal.apply(lambda x: 1 if x > 0 else -1)

        k_over_d = k / d
        k_over_d_signal = k_over_d.apply(lambda x: 1 if x > 0 else -1)
        max_price_shift = natr * 0.8
        srsi_over_signal = d.apply(
            lambda x: -1 if x > 80 else (1 if x < 20 else 0)
        )

        rsi_wma_signal = (rsi - rsi_wma).apply(lambda x: 1 if x > 0 else -1)
        rsi_over_signal = rsi.apply(
            lambda x: -1 if x > 70 else (1 if x < 30 else 0)
        )

        signal_multipliers = [
            # HMA
            hma_very_slow_signal,
            hma_slow_signal,
            hma_fast_signal,
            # SRSI
            k_over_d_signal,
            srsi_over_signal,
            # RSI
            rsi_wma_signal,
            rsi_over_signal,
        ]
        # Create even weights to the signals
        signal_multiplier = sum(
            signal / len(signal_multipliers) for signal in signal_multipliers
        )
        price_multiplier = signal_multiplier * max_price_shift
        return price_multiplier, natr

    async def update_processed_data(self):
        candles = self.market_data_provider.get_candles_df(
            connector_name=self.config.candles_connector,
            trading_pair=self.config.candles_trading_pair,
            interval=self.config.interval,
            max_records=self.max_records,
        )

        price_multiplier, natr = self.get_price_multiplier(
            candles=candles,
            natr_length=self.config.natr_length,
            rsi_length=self.config.rsi_length,
            stoch_rsi_length=self.config.stoch_rsi_length,
            stoch_rsi_smoothing=self.config.stoch_rsi_smoothing,
            hma_very_slow=self.config.hma_very_slow,
            hma_slow=self.config.hma_slow,
            hma_fast=self.config.hma_fast,
        )
        price_multiplier = price_multiplier.iloc[-1]
        candles = candles.copy()
        candles["spread_multiplier"] = natr
        candles["reference_price"] = candles["close"] # * (1 + price_multiplier)
        self.processed_data = {
            "reference_price": Decimal(candles["reference_price"].iloc[-1]),
            "spread_multiplier": Decimal(candles["spread_multiplier"].iloc[-1]),
            "features": candles,
        }

    def get_executor_config(
        self, level_id: str, price: Decimal, amount: Decimal
    ):
        trade_type = self.get_trade_type_from_level_id(level_id)
        # TODO: this "get_executor_config" happens all the time, so we can dynamically change the config!
        # triple_barrier_config is built dyncamically on every access (getter)

        # I want to make the take profit and stop loss dynamic, so it's based on the
        # NATR of the underlying asset, so it can be used for high and low volatility assets


        # natr = Decimal(self.processed_data[f"NATR_{self.config.natr_length}"]) / Decimal(100.0)
        natr = Decimal(self.processed_data["spread_multiplier"]) / Decimal(100.0)

        # TP = 1x NATR
        self.config.take_profit = self.config.tp_natr_factor * natr


        # SL = 1x NATR
        self.config.stop_loss = self.config.sl_natr_factor * natr

        # Trailing Stop 
        self.config.trailing_stop=TrailingStop(
            activation_price=Decimal(self.config.ts_activation_natr_factor * natr), 
            trailing_delta=Decimal(self.config.ts_delta_natr_factor * natr)
        )

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
    
    def get_price_and_amount(self, level_id: str) -> Tuple[Decimal, Decimal]:
        """
        Get the spread and amount in quote for a given level id.
        """
        level = self.get_level_from_level_id(level_id)
        trade_type = self.get_trade_type_from_level_id(level_id)
        spreads, amounts_quote = self.config.get_spreads_and_amounts_in_quote(trade_type)
        # spreads = [1.0, 1.5]
        reference_price = Decimal(self.processed_data["reference_price"])

        spread_in_pct = Decimal(spreads[int(level)]) * Decimal(self.processed_data["spread_multiplier"])
        # spread_multiplier e.g. = 0.0025 (0.25% NATR)
        # spread_in_pct = 1 * 0.0025

        side_multiplier = Decimal("-1") if trade_type == TradeType.BUY else Decimal("1")
        order_price = reference_price * (1 + side_multiplier * spread_in_pct)

        # print (spreads, amounts_quote)
        
        # print(
        #     f"{trade_type}_{level}",
        #     f"{reference_price:.4f}",
        #     f"{spread_in_pct:.4f}",
        #     f"{order_price:.4f}",
        #     f"{Decimal(amounts_quote[int(level)]) / order_price:.4f}"
        # )

        return order_price, Decimal(amounts_quote[int(level)]) / order_price