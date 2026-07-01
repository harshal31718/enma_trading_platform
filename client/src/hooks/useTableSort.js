import { useMemo, useState, useCallback } from 'react'

/**
 * Client-side sort state + row sorting for tables that already hold all rows in memory
 * (Dashboard tables, history lists <=100 rows). For paginated/server-driven tables
 * (OrderHistory, BacktestHistory) use the `sort`/`order` query params instead — see
 * useOrderHistory.js / useBacktestList in useBacktest.js.
 *
 * getValue(row, key) lets callers control how a column value is extracted/compared
 * (defaults to row[key]).
 */
export function useTableSort(rows, { getValue = (row, key) => row[key] } = {}) {
  const [sortState, setSortState] = useState(null) // { key, dir: 'asc' | 'desc' } | null

  const onSort = useCallback((key) => {
    setSortState((prev) => {
      if (!prev || prev.key !== key) return { key, dir: 'asc' }
      if (prev.dir === 'asc') return { key, dir: 'desc' }
      return null // third click clears sort
    })
  }, [])

  const sortedRows = useMemo(() => {
    if (!sortState || !rows) return rows
    const { key, dir } = sortState
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = getValue(a, key)
      const bv = getValue(b, key)
      const an = typeof av === 'string' ? parseFloat(av) : av
      const bn = typeof bv === 'string' ? parseFloat(bv) : bv
      let cmp
      if (Number.isFinite(an) && Number.isFinite(bn)) {
        cmp = an - bn
      } else {
        cmp = String(av ?? '').localeCompare(String(bv ?? ''))
      }
      return dir === 'asc' ? cmp : -cmp
    })
    return copy
  }, [rows, sortState, getValue])

  return { sortedRows, sortState, onSort }
}

export default useTableSort
