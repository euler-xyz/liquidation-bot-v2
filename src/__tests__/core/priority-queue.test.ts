import { describe, test, expect, beforeEach } from 'bun:test';
import { PriorityQueue } from '../../core/priority-queue';
import type { QueueItem } from '../../core/types';

describe('PriorityQueue', () => {
  let queue: PriorityQueue;

  beforeEach(() => {
    queue = new PriorityQueue();
  });

  test('should start empty', () => {
    expect(queue.isEmpty()).toBe(true);
    expect(queue.size()).toBe(0);
    expect(queue.peek()).toBeUndefined();
  });

  test('should add items and maintain min-heap order', () => {
    const item1: QueueItem = {
      address: '0x1111111111111111111111111111111111111111',
      controllerAddress: '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      priority: 100,
    };
    const item2: QueueItem = {
      address: '0x2222222222222222222222222222222222222222',
      controllerAddress: '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      priority: 50,
    };
    const item3: QueueItem = {
      address: '0x3333333333333333333333333333333333333333',
      controllerAddress: '0xcccccccccccccccccccccccccccccccccccccccc',
      priority: 75,
    };

    queue.push(item1);
    queue.push(item2);
    queue.push(item3);

    expect(queue.size()).toBe(3);
    expect(queue.peek()?.priority).toBe(50);
  });

  test('should pop items in priority order', () => {
    queue.push({
      address: '0x1111111111111111111111111111111111111111',
      controllerAddress: '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      priority: 100,
    });
    queue.push({
      address: '0x2222222222222222222222222222222222222222',
      controllerAddress: '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      priority: 50,
    });
    queue.push({
      address: '0x3333333333333333333333333333333333333333',
      controllerAddress: '0xcccccccccccccccccccccccccccccccccccccccc',
      priority: 75,
    });

    expect(queue.pop()?.priority).toBe(50);
    expect(queue.pop()?.priority).toBe(75);
    expect(queue.pop()?.priority).toBe(100);
    expect(queue.pop()).toBeUndefined();
  });

  test('should update existing item priority', () => {
    const address = '0x1111111111111111111111111111111111111111';
    const controller = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

    queue.push({ address, controllerAddress: controller, priority: 100 });
    queue.push({ address, controllerAddress: controller, priority: 50 });

    expect(queue.size()).toBe(1);
    expect(queue.peek()?.priority).toBe(50);
  });

  test('should check if item exists', () => {
    const address = '0x1111111111111111111111111111111111111111';
    const controller = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

    expect(queue.has(address, controller)).toBe(false);

    queue.push({ address, controllerAddress: controller, priority: 100 });

    expect(queue.has(address, controller)).toBe(true);
  });

  test('should get item without removing', () => {
    const address = '0x1111111111111111111111111111111111111111';
    const controller = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

    queue.push({ address, controllerAddress: controller, priority: 100 });

    const item = queue.get(address, controller);
    expect(item?.priority).toBe(100);
    expect(queue.size()).toBe(1);
  });

  test('should remove specific item', () => {
    const address = '0x1111111111111111111111111111111111111111';
    const controller = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

    queue.push({ address, controllerAddress: controller, priority: 100 });
    queue.push({
      address: '0x2222222222222222222222222222222222222222',
      controllerAddress: '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      priority: 50,
    });

    expect(queue.remove(address, controller)).toBe(true);
    expect(queue.size()).toBe(1);
    expect(queue.has(address, controller)).toBe(false);
  });

  test('should get due items', () => {
    const now = Math.floor(Date.now() / 1000);

    queue.push({
      address: '0x1111111111111111111111111111111111111111',
      controllerAddress: '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      priority: now - 100, // past
    });
    queue.push({
      address: '0x2222222222222222222222222222222222222222',
      controllerAddress: '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      priority: now + 100, // future
    });
    queue.push({
      address: '0x3333333333333333333333333333333333333333',
      controllerAddress: '0xcccccccccccccccccccccccccccccccccccccccc',
      priority: now - 50, // past
    });

    const dueItems = queue.getDueItems(now);

    expect(dueItems.length).toBe(2);
    expect(queue.size()).toBe(1);
  });

  test('should clear all items', () => {
    queue.push({
      address: '0x1111111111111111111111111111111111111111',
      controllerAddress: '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      priority: 100,
    });
    queue.push({
      address: '0x2222222222222222222222222222222222222222',
      controllerAddress: '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      priority: 50,
    });

    queue.clear();

    expect(queue.isEmpty()).toBe(true);
    expect(queue.size()).toBe(0);
  });

  test('should convert to and from array', () => {
    const items: QueueItem[] = [
      {
        address: '0x1111111111111111111111111111111111111111',
        controllerAddress: '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        priority: 100,
      },
      {
        address: '0x2222222222222222222222222222222222222222',
        controllerAddress: '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        priority: 50,
      },
    ];

    queue.fromArray(items);

    expect(queue.size()).toBe(2);
    expect(queue.peek()?.priority).toBe(50);

    const array = queue.toArray();
    expect(array.length).toBe(2);
  });
});
