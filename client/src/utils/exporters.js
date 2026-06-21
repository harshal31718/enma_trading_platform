/**
 * Export utilities for backtest results and trades
 */

/**
 * Convert trade objects to CSV string
 * @param {Array} trades - Array of trade objects
 * @returns {string} CSV content
 */
export function tradesToCSV(trades) {
    if (!trades || trades.length === 0) return ''

    // Define columns in order
    const columns = [
        'id',
        'type',
        'qty',
        'entryPrice',
        'exitPrice',
        'entryTime',
        'exitTime',
        'pnl',
        'pnlPct',
        'runUp',
        'drawDown',
        'barsHeld',
    ]

    // CSV header
    const header = columns.join(',')

    // CSV rows
    const rows = trades.map((trade) => {
        return columns
            .map((col) => {
                let value = trade[col] ?? ''

                // Format numbers and dates
                if (typeof value === 'number') {
                    value = value.toFixed(8).replace(/\.?0+$/, '') // Remove trailing zeros
                } else if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
                    // ISO date string — just use as-is
                    value = value
                }

                // Quote values that contain commas, quotes, or newlines
                if (typeof value === 'string' && /[,"\n]/.test(value)) {
                    value = `"${value.replace(/"/g, '""')}"` // Escape quotes by doubling
                }

                return value
            })
            .join(',')
    })

    return [header, ...rows].join('\n')
}

/**
 * Convert full backtest result to JSON string
 * @param {Object} result - Backtest result object
 * @returns {string} JSON content
 */
export function resultToJSON(result) {
    return JSON.stringify(result, null, 2)
}

/**
 * Trigger browser download for CSV or JSON
 * @param {string} content - File content
 * @param {string} filename - Desired filename (without extension)
 * @param {string} type - File type ('csv' or 'json')
 */
export function downloadFile(content, filename, type = 'csv') {
    const extension = type === 'json' ? '.json' : '.csv'
    const mimeType = type === 'json' ? 'application/json' : 'text/csv;charset=utf-8;'

    const blob = new Blob([content], { type: mimeType })
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)

    link.href = url
    link.download = `${filename}${extension}`

    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
}

/**
 * Export trades to CSV file
 * @param {Array} trades - Array of trade objects
 * @param {string} resultId - Backtest result ID for filename
 * @param {string} strategy - Strategy name for filename
 */
export function exportTradesAsCSV(trades, resultId, strategy) {
    const csv = tradesToCSV(trades)
    if (!csv) {
        console.warn('No trades to export')
        return
    }

    const timestamp = new Date().toISOString().slice(0, 10)
    const filename = `backtest_trades_${strategy}_${timestamp}`

    downloadFile(csv, filename, 'csv')
}

/**
 * Export full backtest result to JSON file
 * @param {Object} result - Full backtest result object
 * @param {string} strategy - Strategy name for filename
 */
export function exportResultAsJSON(result, strategy) {
    const json = resultToJSON(result)

    const timestamp = new Date().toISOString().slice(0, 10)
    const filename = `backtest_result_${strategy}_${timestamp}`

    downloadFile(json, filename, 'json')
}
