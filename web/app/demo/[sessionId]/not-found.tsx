import Link from 'next/link';

export default function SessionNotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-950 p-6 text-slate-300">
      <div className="max-w-md rounded-lg border border-slate-800 bg-slate-900 p-8 text-center shadow-lg">
        <h1 className="mb-4 text-2xl font-semibold text-white">Session Not Found</h1>
        <p className="mb-8 text-slate-400">
          The requested demo session could not be found or failed to load.
        </p>
        <Link 
          href="/demo"
          className="inline-block rounded-md bg-emerald-600 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
        >
          Back to Demo Picker
        </Link>
      </div>
    </div>
  );
}
