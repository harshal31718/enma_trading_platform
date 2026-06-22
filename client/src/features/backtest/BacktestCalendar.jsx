import { useState, useMemo } from 'react';
import { cn } from "@/lib/utils";
import {
    getDailyStats,
    getWeeklyStats,
    getMonthlyStats,
    getQuarterlyStats
} from "@/utils/backtest-analytics";
import { Calendar as CalendarIcon } from "lucide-react";

export default function BacktestCalendar({ trades, onSelectPeriod }) {
    const [view, setView] = useState('QUARTERLY');
    const [selectedId, setSelectedId] = useState(null);

    // Compute stats based on current view
    const stats = useMemo(() => {
        if (!trades || !trades.length) return [];
        switch (view) {
            case 'DAILY': return getDailyStats(trades);
            case 'WEEKLY': return getWeeklyStats(trades);
            case 'MONTHLY': return getMonthlyStats(trades);
            case 'QUARTERLY': return getQuarterlyStats(trades);
            default: return [];
        }
    }, [view, trades]);

    // Find min/max PnL for color intensity
    const { maxWin, maxLoss } = useMemo(() => {
        let maxWin = 0;
        let maxLoss = 0;
        stats.forEach(s => {
            if (s.pnl > maxWin) maxWin = s.pnl;
            if (s.pnl < maxLoss) maxLoss = s.pnl;
        });
        return { maxWin, maxLoss };
    }, [stats]);

    // Helper to get color style
    const getCellStyle = (pnl) => {
        const isWin = pnl >= 0;
        const max = isWin ? maxWin : Math.abs(maxLoss);
        const intensity = max === 0 ? 0 : Math.min(Math.abs(pnl) / max, 1);

        // Base colors: Green-500 (#22c55e), Red-500 (#ef4444)
        // Using emerald-400 as per AGENTS.md constraints
        const baseColor = isWin ? '52, 211, 153' : '248, 113, 113';

        return {
            backgroundColor: `rgba(${baseColor}, ${0.1 + (intensity * 0.4)})`,
            borderColor: `rgba(${baseColor}, ${0.3 + (intensity * 0.5)})`,
        };
    };

    const handleSelect = (stat) => {
        if (selectedId === stat.id) {
            setSelectedId(null);
            if (onSelectPeriod) onSelectPeriod(null);
        } else {
            setSelectedId(stat.id);
            if (onSelectPeriod) onSelectPeriod(stat.trades);
        }
    };

    return (
        <div className="flex flex-col h-full bg-title-bg border border-slate-700/50 overflow-hidden">
            {/* Header */}
            <div className="h-11 title-fade flex items-center justify-between px-4 border-b border-slate-700/30 shrink-0">
                <div className="flex items-center gap-2 text-gray-200 font-semibold text-sm">
                    <CalendarIcon className="size-4 text-emerald-400" />
                    <span>Performance Calendar</span>
                </div>

                <div className="flex bg-gray-950 rounded-lg p-0.5 border border-gray-800">
                    {['QUARTERLY', 'MONTHLY', 'WEEKLY', 'DAILY'].map(t => (
                        <button
                            key={t}
                            onClick={() => { setView(t); setSelectedId(null); if (onSelectPeriod) onSelectPeriod(null) }}
                            className={cn(
                                "px-3 py-1 text-[10px] font-bold rounded-md transition-all",
                                view === t
                                    ? "bg-gray-800 text-white shadow-sm"
                                    : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
                            )}
                        >
                            {t}
                        </button>
                    ))}
                </div>
            </div>

            {/* Content - Expanded to fit */}
            <div className="max-h-[500px] overflow-y-auto p-4">
                <div className={cn(
                    "grid gap-2 content-start",
                    view === 'QUARTERLY' && "grid-cols-2 md:grid-cols-4",
                    view === 'MONTHLY' && "grid-cols-2 md:grid-cols-4",
                    view === 'WEEKLY' && "grid-cols-2 md:grid-cols-4",
                    view === 'DAILY' && "grid-cols-4 md:grid-cols-7"
                )}>
                    {stats.map(stat => (
                        <div
                            key={stat.id}
                            onClick={() => handleSelect(stat)}
                            style={getCellStyle(stat.pnl)}
                            className={cn(
                                "relative rounded p-3 cursor-pointer transition-all border hover:brightness-110 active:scale-95 flex flex-col justify-between min-h-[85px]",
                                selectedId === stat.id ? "ring-2 ring-emerald-500 z-10 brightness-125" : "border-transparent"
                            )}
                        >
                            {/* Top Row: Date | Trades */}
                            <div className="flex justify-between items-center text-[10px] font-bold text-gray-400 uppercase">
                                <span className="truncate pr-1">{stat.label}</span>
                                <span className="text-gray-500 font-mono flex-shrink-0">{stat.tradesCount}t</span>
                            </div>

                            {/* Bottom Row: PnL | Win Rate (as %) */}
                            <div className="flex justify-between items-end mt-2">
                                <div className={cn("text-sm font-black font-mono leading-none", stat.pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                                    {stat.pnl >= 0 ? '+' : ''}{stat.pnl.toFixed(0)}
                                </div>
                                {stat.winRate > 0 && (
                                    <div className="text-[10px] text-gray-500 font-mono font-bold">
                                        {(stat.winRate * 100).toFixed(0)}%
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                    {!stats.length && (
                        <div className="col-span-full py-12 text-center text-gray-500 text-sm italic">
                            No trades found for this backtest.
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
