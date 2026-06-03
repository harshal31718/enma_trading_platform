export default function PageWrapper({ children }) {
  return (
    <main className="min-h-screen bg-gray-950 pt-[56px]">
      <div className="p-6">{children}</div>
    </main>
  )
}
