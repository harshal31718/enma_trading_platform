import { useMemo } from 'react';
import { cn } from '@/lib/utils';
import { Calendar as CalendarIcon } from 'lucide-react';

/**
 * Lightweight day-view P&L heatmap for the Dashboard.
 *
 * Operates on a pre-aggregated `days` array (one entry per calendar day)
 * from /api/v1/dashboard/performance-calendar — no per-trade math here.
 *
 * Props:
 *   days: [{ date: 'YYYY-MM-DD', pnl: number, trades: number }]
 *   timeframe: '30d' | '90d' | 'all' — client-side filter on `days`
 */
export default function DashboardCalendar({ days = [], timeframe = 'all' }) {
    const filtered = useMemo(() => {
        if (!days || days.length === 0) return [];
        if (timeframe === 'all') return days;

        const cutoffDays = timeframe === '30d' ? 30 : 90;
        const cutoff = new Date();
        cutoff.setUTCHours(0, 0, 0, 0);
        cutoff.setUTCDate(cutoff.getUTCDate() - cutoffDays);

        return days.filter((d) => {
            // d.date is 'YYYY-MM-DD' — compare as UTC midnight
            const dayDate = new Date(`${d.date}T00:00:00Z`);
            return dayDate >= cutoff;
        });
    }, [days, timeframe]);

    const { maxWin, maxLoss } = useMemo(() => {
        let winMax = 0;
        let lossMax = 0;
        filtered.forEach((d) => {
            if (d.pnl > winMax) winMax = d.pnl;
            if (d.pnl < lossMax) lossMax = d.pnl;
        });
        return { maxWin: winMax, maxLoss: lossMax };
    }, [filtered]);

    const getCellStyle = (pnl) => {
        const isWin = pnl >= 0;
        const max = isWin ? maxWin : Math.abs(maxLoss);
        const raw = max === 0 ? 0 : Math.min(Math.abs(pnl) / max, 1);
        const t = Math.sqrt(raw);

        const lerp = (a, b) => Math.round(a + (b - a) * t);
        const [lo, hi, edge] = isWin
            ? [[6, 50, 40], [5, 150, 105], '52, 211, 153']   // → emerald-600 → emerald-400
            : [[60, 16, 16], [220, 38, 38], '248, 113, 113']; // → red-600 → red-400

        return {
            backgroundColor: `rgb(${lerp(lo[0], hi[0])}, ${lerp(lo[1], hi[1])}, ${lerp(lo[2], hi[2])})`,
            borderColor: `rgb(${edge})`,
        };
    };

    return (
        <div className="bg-title-bg border border-slate-700/50">
            <div className="h-11 title-fade flex items-center justify-between px-4 border-b border-slate-700/30">
                <div className="flex items-center gap-2 text-gray-200 font-semibold text-sm">
                    <CalendarIcon className="size-4 text-emerald-400" />
                    <span>Performance Calendar</span>
                </div>
                <span className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">
                    {filtered.length} day{filtered.length === 1 ? '' : 's'}
                </span>
            </div>

            <div className="max-h-[320px] overflow-y-auto p-3">
                {filtered.length === 0 ? (
                    <div className="py-12 text-center text-gray-500 text-sm italic">
                        No trades recorded in this window.
                    </div>
                ) : (
                    <div className="grid grid-cols-7 gap-1.5">
                        {filtered.map((d) => (
                            <div
                                key={d.date}
                                style={getCellStyle(d.pnl)}
                                className={cn(
                                    'relative border border-transparent rounded-sm cursor-default flex flex-col justify-between min-h-[44px] p-1.5 hover:brightness-110'
                                )}
                                title={`${d.date} — ${d.trades} trade${d.trades === 1 ? '' : 's'} — P&L ${d.pnl >= 0 ? '+' : ''}${d.pnl.toFixed(2)}`}
                            >
                                <div className="flex justify-between items-center text-[9px] font-bold text-white/85 uppercase leading-none">
                                    <span className="font-mono">{d.date.slice(5)}</span>
                                    <span className="text-white/65 font-mono">{d.trades}t</span>
                                </div>
                                <div className="text-[11px] font-black font-mono leading-none text-white mt-1 [text-shadow:0_1px_2px_rgba(0,0,0,0.45)]">
                                    {d.pnl >= 0 ? '+' : ''}{d.pnl.toFixed(0)}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
