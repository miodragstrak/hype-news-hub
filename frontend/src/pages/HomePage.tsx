import { useBackendStatus } from "../hooks/useBackendStatus";

export function HomePage() {
  const { data, isLoading, error } = useBackendStatus();

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center px-6 text-center">
      <h1 className="text-4xl font-bold tracking-tight">Hype News Hub</h1>

      <section className="mt-8 w-full rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold">Backend Status</h2>

        {isLoading && <p className="mt-3 text-slate-600">Checking backend...</p>}

        {error && <p className="mt-3 text-red-600">{error}</p>}

        {data && (
          <div className="mt-3 space-y-1 text-slate-700">
            <p>
              <span className="font-medium">Name:</span> {data.name}
            </p>
            <p>
              <span className="font-medium">Status:</span> {data.status}
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
