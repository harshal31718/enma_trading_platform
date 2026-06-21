import { useEffect, useMemo, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { useStrategyParams, useCreateStrategy } from '../../hooks/useStrategies'

const STRATEGY_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]+$/

export default function StrategyCreateDialog({
    open,
    onOpenChange,
    strategies = [],
    defaultMode = 'blank',
    defaultSourceId = '',
}) {
    const [mode, setMode] = useState(defaultMode)
    const [name, setName] = useState('')
    const [description, setDescription] = useState('')
    const [sourceStrategyId, setSourceStrategyId] = useState(defaultSourceId)
    const [errorMessage, setErrorMessage] = useState('')

    const { data: sourceParams } = useStrategyParams(sourceStrategyId)
    const sourceStrategy = useMemo(
        () => strategies.find((strategy) => strategy.id === sourceStrategyId),
        [strategies, sourceStrategyId]
    )

    const createStrategyMutation = useCreateStrategy()
    const canSubmit = Boolean(name.trim() && (mode === 'blank' || (mode === 'clone' && sourceStrategyId)))

    useEffect(() => {
        if (!open) {
            setMode('blank')
            setName('')
            setDescription('')
            setSourceStrategyId('')
            setErrorMessage('')
            return
        }

        setMode(defaultMode)
        setSourceStrategyId(defaultSourceId)
        setErrorMessage('')
    }, [open, defaultMode, defaultSourceId])
    const handleCreate = async () => {
        setErrorMessage('')
        if (!name.trim()) {
            setErrorMessage('Strategy name is required.')
            return
        }
        if (!STRATEGY_NAME_PATTERN.test(name.trim())) {
            setErrorMessage('Name must start with a letter and only contain letters, numbers, and underscores.')
            return
        }
        if (mode === 'clone' && !sourceStrategyId) {
            setErrorMessage('Select a source strategy to clone.')
            return
        }

        try {
            await createStrategyMutation.mutateAsync({
                name: name.trim(),
                description: description.trim(),
                sourceName: mode === 'clone' ? sourceStrategy?.name : undefined,
                template: mode === 'blank' ? 'blank' : undefined,
            })
            onOpenChange(false)
        } catch (err) {
            setErrorMessage(err?.response?.data?.error?.message || err.message || 'Failed to create strategy.')
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl bg-gray-900 border border-gray-800">
                <DialogHeader>
                    <DialogTitle>Create New Strategy</DialogTitle>
                    <DialogDescription>
                        Scaffold a new strategy or clone an existing one. New strategies use the black-box forecast() pattern and are stored on the engine.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4 mt-4">
                    <div className="grid gap-3 sm:grid-cols-2">
                        <button
                            type="button"
                            className={`rounded-lg border p-3 text-left ${mode === 'blank' ? 'border-emerald-500 bg-emerald-500/10' : 'border-gray-800 bg-gray-950 hover:border-gray-700'}`}
                            onClick={() => setMode('blank')}
                        >
                            <div className="text-sm font-medium text-gray-100">Blank template</div>
                            <p className="text-sm text-gray-400 mt-1">Start from a minimal strategy scaffold with forecast() only.</p>
                        </button>
                        <button
                            type="button"
                            className={`rounded-lg border p-3 text-left ${mode === 'clone' ? 'border-emerald-500 bg-emerald-500/10' : 'border-gray-800 bg-gray-950 hover:border-gray-700'}`}
                            onClick={() => setMode('clone')}
                        >
                            <div className="text-sm font-medium text-gray-100">Clone existing strategy</div>
                            <p className="text-sm text-gray-400 mt-1">Duplicate a seeded strategy and keep the same parameter schema.</p>
                        </button>
                    </div>

                    <div className="grid gap-4">
                        <div>
                            <label className="text-sm text-gray-300 mb-1 block">Strategy name</label>
                            <Input
                                value={name}
                                onChange={(event) => setName(event.target.value)}
                                placeholder="ExampleStrategy"
                            />
                        </div>
                        <div>
                            <label className="text-sm text-gray-300 mb-1 block">Description</label>
                            <Input
                                value={description}
                                onChange={(event) => setDescription(event.target.value)}
                                placeholder="Optional description"
                            />
                        </div>

                        {mode === 'clone' && (
                            <div>
                                <label className="text-sm text-gray-300 mb-1 block">Source strategy</label>
                                <Select value={sourceStrategyId} onChange={(event) => setSourceStrategyId(event.target.value)}>
                                    <option value="">Choose a strategy</option>
                                    {strategies.map((strategy) => (
                                        <option key={strategy.id} value={strategy.id}>
                                            {strategy.name}
                                        </option>
                                    ))}
                                </Select>
                            </div>
                        )}

                        {mode === 'clone' && sourceStrategy && sourceParams && (
                            <div className="rounded-lg border border-gray-800 bg-gray-950 p-4">
                                <p className="text-sm text-gray-100 font-medium">Parameter preview for {sourceStrategy.name}</p>
                                <div className="grid gap-2 mt-3">
                                    {Object.entries(sourceParams).map(([key, meta]) => (
                                        <div key={key} className="rounded border border-gray-800 bg-gray-900 p-3">
                                            <div className="text-sm text-gray-200 font-medium">{meta.label || key}</div>
                                            <div className="text-xs text-gray-400 mt-1">default: {String(meta.default)}{meta.min !== undefined ? ` | min: ${meta.min}` : ''}{meta.max !== undefined ? ` | max: ${meta.max}` : ''}</div>
                                        </div>
                                    ))}
                                    {Object.keys(sourceParams).length === 0 && (
                                        <p className="text-sm text-gray-400">No configurable parameters were detected for this strategy.</p>
                                    )}
                                </div>
                            </div>
                        )}

                        <div className="rounded-lg border border-gray-800 bg-gray-950 p-4 text-sm text-gray-400">
                            <p className="font-medium text-gray-100">Authoring guidance</p>
                            <p className="mt-2">New strategies should implement <code className="rounded bg-gray-900 px-1 py-0.5">forecast()</code> only and avoid direct order writes inside the strategy body. The engine owns execution, risk, portfolio sizing, and stop/target planning.</p>
                        </div>

                        {errorMessage && (
                            <p className="text-sm text-red-400">{errorMessage}</p>
                        )}
                    </div>
                </div>

                <DialogFooter className="mt-4 gap-2">
                    <Button variant="secondary" onClick={() => onOpenChange(false)} type="button">
                        Cancel
                    </Button>
                    <Button variant="default" onClick={handleCreate} disabled={!canSubmit || createStrategyMutation.isLoading}>
                        {createStrategyMutation.isLoading ? 'Creating...' : 'Create strategy'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
