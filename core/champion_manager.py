"""
ChampionManager — Global, persistent champion tracking per symbol.

Replaces session-local champion tracking with database-backed records.
Enables multi-symbol champions (best EURUSD, best GBPUSD, best USDJPY).

Key methods:
- get_global_champion(symbol) → BacktestResult or None
- promote_if_better(result, symbol) → bool
- get_champion_history(symbol, limit) → List[BacktestResult]
- export_champion(symbol) → file path
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.strategy_config import BacktestResult
from core.database import GlobalChampion, Base

logger = logging.getLogger(__name__)


class ChampionManager:
    """Manages persistent per-symbol champions."""

    def __init__(self, db_url: str):
        """Initialize with database URL."""
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)

    def get_global_champion(self, symbol: str) -> Optional[Dict]:
        """
        Fetch current global champion for a symbol.

        Args:
            symbol: Trading pair (e.g., "EURUSD")

        Returns:
            Dict with champion metadata or None if not found
        """
        with Session(self.engine) as session:
            champ = session.query(GlobalChampion).filter_by(symbol=symbol).first()
            if champ is None:
                logger.info("No global champion found for %s", symbol)
                return None

            return {
                'symbol': champ.symbol,
                'version': champ.strategy_version,
                'profit_factor': champ.profit_factor,
                'max_drawdown_pct': champ.max_drawdown_pct,
                'recovery_factor': champ.recovery_factor,
                'avg_win_loss_ratio': champ.avg_win_loss_ratio,
                'meets_all_targets': champ.meets_all_targets,
                'file_path': champ.file_path,
                'promoted_at': champ.promoted_at,
            }

    def promote_if_better(self, result: BacktestResult, symbol: str) -> bool:
        """
        Compare against DB champion; promote to champion if better.

        Promotion criteria: profit_factor > current champion's PF.

        Args:
            result: BacktestResult from completed backtest
            symbol: Trading pair (e.g., "EURUSD")

        Returns:
            True if promoted, False otherwise
        """
        with Session(self.engine) as session:
            current_champ = session.query(GlobalChampion).filter_by(symbol=symbol).first()

            # Check if this result is better
            if current_champ is None:
                is_better = True
                logger.info("First champion for %s: %s (PF=%.2f)", symbol, result.version, result.profit_factor)
            elif result.profit_factor > current_champ.profit_factor:
                is_better = True
                logger.info(
                    "New champion for %s: %s (PF=%.2f > %.2f)",
                    symbol, result.version, result.profit_factor, current_champ.profit_factor,
                )
            else:
                is_better = False
                logger.debug(
                    "No promotion for %s: %s (PF=%.2f <= %.2f)",
                    symbol, result.version, result.profit_factor, current_champ.profit_factor,
                )

            if is_better:
                # Create or update champion
                if current_champ:
                    current_champ.symbol = symbol
                    current_champ.strategy_version = result.version
                    current_champ.promoted_at = datetime.utcnow()
                    current_champ.file_path = result.file_path
                    current_champ.profit_factor = result.profit_factor
                    current_champ.max_drawdown_pct = result.max_drawdown_pct
                    current_champ.recovery_factor = result.recovery_factor
                    current_champ.avg_win_loss_ratio = result.avg_win_loss_ratio
                    current_champ.meets_all_targets = result.meets_all_targets
                else:
                    current_champ = GlobalChampion(
                        symbol=symbol,
                        strategy_version=result.version,
                        promoted_at=datetime.utcnow(),
                        file_path=result.file_path,
                        profit_factor=result.profit_factor,
                        max_drawdown_pct=result.max_drawdown_pct,
                        recovery_factor=result.recovery_factor,
                        avg_win_loss_ratio=result.avg_win_loss_ratio,
                        meets_all_targets=result.meets_all_targets,
                    )
                    session.add(current_champ)

                session.commit()
                return True

        return False

    def get_champion_history(self, symbol: str, limit: int = 10) -> List[Dict]:
        """
        Get historical champion records (promotions over time).

        Note: Currently only stores the latest champion. For full history,
        would need a separate history table. This is a placeholder.

        Args:
            symbol: Trading pair
            limit: Max records to return

        Returns:
            List of champion dicts (newest first)
        """
        champ = self.get_global_champion(symbol)
        if champ:
            return [champ]
        return []

    def get_all_champions(self) -> Dict[str, Dict]:
        """
        Fetch all current champions (one per symbol).

        Returns:
            Dict mapping symbol → champion metadata
        """
        with Session(self.engine) as session:
            champs = session.query(GlobalChampion).all()
            return {
                champ.symbol: {
                    'symbol': champ.symbol,
                    'version': champ.strategy_version,
                    'profit_factor': champ.profit_factor,
                    'max_drawdown_pct': champ.max_drawdown_pct,
                    'recovery_factor': champ.recovery_factor,
                    'avg_win_loss_ratio': champ.avg_win_loss_ratio,
                    'meets_all_targets': champ.meets_all_targets,
                    'file_path': champ.file_path,
                    'promoted_at': champ.promoted_at,
                }
                for champ in champs
            }
