import { notFound } from 'next/navigation';
import { readFile } from 'fs/promises';
import { join } from 'path';
import { Session } from '../../../lib/types/session';
import DemoReplayClient from './demo-replay-client';

interface PageProps {
  params: Promise<{ sessionId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function DemoSessionPage({ params, searchParams }: PageProps) {
  const resolvedParams = await params;
  const resolvedSearchParams = await searchParams;
  const { sessionId } = resolvedParams;

  let session: Session;

  try {
    const filePath = join(process.cwd(), 'public', 'samples', `${sessionId}_session.json`);
    const fileContent = await readFile(filePath, 'utf-8');
    session = JSON.parse(fileContent) as Session;
  } catch (error) {
    notFound();
  }

  // Parse speed from search params
  let speed: 1 | 2 | 4 | 10 = 4; // Default
  const speedParam = resolvedSearchParams.speed;
  if (typeof speedParam === 'string') {
    if (speedParam === 'instant') {
      speed = 10; // For now treat instant as max speed, or handle differently later
    } else {
      const parsed = parseInt(speedParam, 10);
      if (parsed === 1 || parsed === 2 || parsed === 4 || parsed === 10) {
        speed = parsed;
      }
    }
  }

  // Parse start from search params
  let startT = 0;
  const startParam = resolvedSearchParams.start;
  if (typeof startParam === 'string') {
    const parsedStart = parseFloat(startParam);
    if (!isNaN(parsedStart) && parsedStart >= 0) {
      startT = parsedStart;
    }
  }

  return (
    <DemoReplayClient 
      session={session} 
      sessionId={sessionId} 
      initialSpeed={speed}
      initialT={startT}
    />
  );
}
