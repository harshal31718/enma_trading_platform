/**
 * Utility functions for aggregating backtest trade results into timeframes
 * for the BacktestCalendar component.
 */

export function getDailyStats(trades) {
    return aggregateStats(trades, (date) => {
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }, (date) => {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return `${months[date.getMonth()]} ${date.getDate()}`;
    });
}

export function getWeeklyStats(trades) {
    return aggregateStats(trades, (date) => {
        const d = new Date(date);
        d.setHours(0, 0, 0, 0);
        d.setDate(d.getDate() + 4 - (d.getDay() || 7));
        const yearStart = new Date(d.getFullYear(), 0, 1);
        const weekNo = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
        return `${d.getFullYear()}-W${String(weekNo).padStart(2, '0')}`;
    }, (date) => {
        const d = new Date(date);
        d.setDate(d.getDate() - (d.getDay() || 7) + 1); // Start of week (Monday)
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return `Wk of ${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
    });
}

export function getMonthlyStats(trades) {
    return aggregateStats(trades, (date) => {
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        return `${y}-${m}`;
    }, (date) => {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return `${months[date.getMonth()]} ${date.getFullYear()}`;
    });
}

export function getQuarterlyStats(trades) {
    return aggregateStats(trades, (date) => {
        const y = date.getFullYear();
        const q = Math.floor(date.getMonth() / 3) + 1;
        return `${y}-Q${q}`;
    }, (date) => {
        const q = Math.floor(date.getMonth() / 3) + 1;
        return `Q${q} ${date.getFullYear()}`;
    });
}

function aggregateStats(trades, groupKeyFn, labelFormatFn) {
    if (!trades || !trades.length) return [];

    const groups = {};

    trades.forEach(trade => {
        const date = new Date(trade.exitAt || trade.entryAt);
        const key = groupKeyFn(date);

        if (!groups[key]) {
            groups[key] = {
                id: key,
                label: labelFormatFn(date),
                pnl: 0,
                tradesCount: 0,
                winningTrades: 0,
                trades: []
            };
        }

        const pnl = parseFloat(trade.pnl || 0);
        groups[key].pnl += pnl;
        groups[key].tradesCount += 1;
        if (pnl > 0) groups[key].winningTrades += 1;
        groups[key].trades.push(trade);
    });

    return Object.values(groups)
        .sort((a, b) => b.id.localeCompare(a.id))
        .map(group => ({
            ...group,
            winRate: group.tradesCount > 0 ? group.winningTrades / group.tradesCount : 0
        }));
}
