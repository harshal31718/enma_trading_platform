export default function PageWrapper({ children }) {
  return (
    <main className="min-h-screen bg-[#060a0f] pt-[56px]">
      <div className="p-6">{children}</div>
    </main>
  )
}
