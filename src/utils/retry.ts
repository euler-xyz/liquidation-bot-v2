import { logger } from './logger';

export interface RetryOptions {
  maxRetries: number;
  baseDelay: number;
  maxDelay?: number;
  exponentialBase?: number;
  jitter?: boolean;
  onRetry?: (error: Error, attempt: number) => void;
}

const DEFAULT_OPTIONS: Required<Omit<RetryOptions, 'onRetry'>> & { onRetry?: RetryOptions['onRetry'] } = {
  maxRetries: 3,
  baseDelay: 1000,
  maxDelay: 30000,
  exponentialBase: 2,
  jitter: true,
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function calculateDelay(attempt: number, options: Required<Omit<RetryOptions, 'onRetry'>>): number {
  const exponentialDelay = options.baseDelay * Math.pow(options.exponentialBase, attempt);
  const cappedDelay = Math.min(exponentialDelay, options.maxDelay);

  if (options.jitter) {
    // Add ±20% jitter
    const jitterFactor = 0.8 + Math.random() * 0.4;
    return Math.floor(cappedDelay * jitterFactor);
  }

  return cappedDelay;
}

export async function withRetry<T>(
  fn: () => Promise<T>,
  options: Partial<RetryOptions> = {}
): Promise<T> {
  const opts = { ...DEFAULT_OPTIONS, ...options };
  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= opts.maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));

      if (attempt === opts.maxRetries) {
        break;
      }

      const delay = calculateDelay(attempt, opts);

      if (opts.onRetry) {
        opts.onRetry(lastError, attempt + 1);
      } else {
        logger.warn(
          { error: lastError.message, attempt: attempt + 1, nextRetryIn: delay },
          'Retrying after error'
        );
      }

      await sleep(delay);
    }
  }

  throw lastError;
}

export async function withTimeout<T>(
  fn: () => Promise<T>,
  timeoutMs: number,
  timeoutMessage = 'Operation timed out'
): Promise<T> {
  return Promise.race([
    fn(),
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs)
    ),
  ]);
}

export async function withRetryAndTimeout<T>(
  fn: () => Promise<T>,
  options: Partial<RetryOptions> & { timeout?: number } = {}
): Promise<T> {
  const { timeout = 30000, ...retryOptions } = options;

  return withRetry(
    () => withTimeout(fn, timeout),
    retryOptions
  );
}
