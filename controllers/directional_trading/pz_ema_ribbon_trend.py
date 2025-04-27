"""
This strategy is a trend following streatgy

Long: EMA10 > EMA20 > EMA30 > EMA40
Short: EMA10 < EMA20 < EMA30 < EMA40

Exit:
When Entry condition nicht mehr gegeben
"""

from decimal import Decimal
from typing import List
from hummingbot.strategy_v2.models.executor_actions import ExecutorAction, StopExecutorAction
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo

import pandas_ta as ta  # noqa: F401
from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.core.data_type.common import TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig
from pydantic import Field, validator


class PZEmaRibbonTrendControllerConfig(DirectionalTradingControllerConfigBase):
    controller_name = "pz_ema_ribbon_trend"
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
    ema_1: int = 50
    ema_2: int = 100
    ema_3: int = 100
    ema_4: int = 100
    
    
    natr_length: int = 14



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


class PZEmaRibbonTrendController(DirectionalTradingControllerBase):

    def __init__(self, config: PZEmaRibbonTrendControllerConfig, *args, **kwargs):
        self.config = config
        self.max_records = max(
            config.natr_length,
            config.ema_1,
            config.ema_2,
            config.ema_3,
            config.ema_4,
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
        df.ta.ema(length=self.config.ema_1, append=True)
        df.ta.ema(length=self.config.ema_2, append=True)
        df.ta.ema(length=self.config.ema_3, append=True)
        df.ta.ema(length=self.config.ema_4, append=True)
        df.ta.natr(length=self.config.natr_length, append=True)

        # Get Dataframe values
        ema_1 = df[f"EMA_{self.config.ema_1}"]
        ema_2 = df[f"EMA_{self.config.ema_2}"]
        ema_3 = df[f"EMA_{self.config.ema_3}"]
        ema_4 = df[f"EMA_{self.config.ema_4}"]

        # Long condition
        long_condition = (ema_1 > ema_2) & (ema_2 > ema_3)  & (ema_3 > ema_4)
        

        # Short Condition
        short_condition = (ema_1 < ema_2) & (ema_2 < ema_3)  & (ema_3 < ema_4)


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

        # natr = Decimal(self.processed_data[f"NATR_{self.config.natr_length}"]) / Decimal(100.0)
        close = Decimal(self.processed_data["close"])
        ema_4 = Decimal(self.processed_data[f"EMA_{self.config.ema_4}"])
        sl = Decimal(abs(close/ema_4))
        # 
        if sl > Decimal(1.0):
            sl -= Decimal(-1.0)

        # SL = Factor * NATR
        self.config.stop_loss = Decimal(sl) # self.config.sl_natr_factor * natr
        # TP = Factor * NATR
        self.config.take_profit = None # self.config.tp_natr_factor * natr
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

        ema_1 = self.processed_data[f"EMA_{self.config.ema_1}"]
        ema_2 = self.processed_data[f"EMA_{self.config.ema_2}"]
        ema_3 = self.processed_data[f"EMA_{self.config.ema_3}"]
        ema_4 = self.processed_data[f"EMA_{self.config.ema_4}"]


        # Long Exit
        long_exit_signal = not ((ema_1 > ema_2) & (ema_2 > ema_3) & (ema_3 > ema_4))
        

        # Short Exit
        short_exit_signal = not( (ema_1 < ema_2) & (ema_2 < ema_3)  & (ema_3 < ema_4))

        
        active_longs, active_shorts = self.get_active_executors_by_side(self.config.connector_name,
                                                                        self.config.trading_pair)
        
        if len(active_longs) > 0 and long_exit_signal:
            stop_actions.extend([StopExecutorAction(executor_id=e.id) for e in active_longs])
        if len(active_shorts) > 0 and short_exit_signal:
            stop_actions.extend([StopExecutorAction(executor_id=e.id) for e in active_shorts])

        return stop_actions