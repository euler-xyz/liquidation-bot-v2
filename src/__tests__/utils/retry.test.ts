import { describe, test, expect } from 'bun:test';
import { withRetry, withTimeout } from '../../utils/retry';

describe('withRetry', () => {
  test('should return result on success', async () => {
    const result = await withRetry(async () => 'success');
    expect(result).toBe('success');
  });

  test('should retry on failure and eventually succeed', async () => {
    let attempts = 0;
    const result = await withRetry(
      async () => {
        attempts++;
        if (attempts < 3) {
          throw new Error('Failed');
        }
        return 'success';
      },
      { maxRetries: 3, baseDelay: 10 }
    );

    expect(result).toBe('success');
    expect(attempts).toBe(3);
  });

  test('should throw after max retries', async () => {
    let attempts = 0;

    await expect(
      withRetry(
        async () => {
          attempts++;
          throw new Error('Always fails');
        },
        { maxRetries: 2, baseDelay: 10 }
      )
    ).rejects.toThrow('Always fails');

    expect(attempts).toBe(3); // Initial + 2 retries
  });

  test('should call onRetry callback', async () => {
    let retryCount = 0;

    try {
      await withRetry(
        async () => {
          throw new Error('Failed');
        },
        {
          maxRetries: 2,
          baseDelay: 10,
          onRetry: () => {
            retryCount++;
          },
        }
      );
    } catch {
      // Expected to throw
    }

    expect(retryCount).toBe(2);
  });
});

describe('withTimeout', () => {
  test('should return result before timeout', async () => {
    const result = await withTimeout(async () => 'success', 1000);
    expect(result).toBe('success');
  });

  test('should throw on timeout', async () => {
    await expect(
      withTimeout(
        async () => {
          await new Promise((resolve) => setTimeout(resolve, 100));
          return 'success';
        },
        10,
        'Operation timed out'
      )
    ).rejects.toThrow('Operation timed out');
  });
});
