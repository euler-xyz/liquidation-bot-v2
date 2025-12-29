import type { Address } from 'viem';
import type { QueueItem } from './types';

/**
 * Min-heap priority queue for scheduling account updates.
 * Items are ordered by priority (Unix timestamp), with lowest priority first.
 */
export class PriorityQueue {
  private heap: QueueItem[] = [];
  private itemMap: Map<string, number> = new Map(); // address:controller -> heap index

  private getKey(address: Address, controllerAddress: Address): string {
    return `${address.toLowerCase()}:${controllerAddress.toLowerCase()}`;
  }

  private parent(i: number): number {
    return Math.floor((i - 1) / 2);
  }

  private leftChild(i: number): number {
    return 2 * i + 1;
  }

  private rightChild(i: number): number {
    return 2 * i + 2;
  }

  private swap(i: number, j: number): void {
    const itemI = this.heap[i];
    const itemJ = this.heap[j];

    if (itemI && itemJ) {
      this.heap[i] = itemJ;
      this.heap[j] = itemI;

      const keyI = this.getKey(itemI.address, itemI.controllerAddress);
      const keyJ = this.getKey(itemJ.address, itemJ.controllerAddress);

      this.itemMap.set(keyI, j);
      this.itemMap.set(keyJ, i);
    }
  }

  private heapifyUp(i: number): void {
    while (i > 0) {
      const parentIdx = this.parent(i);
      const current = this.heap[i];
      const parentItem = this.heap[parentIdx];

      if (current && parentItem && current.priority < parentItem.priority) {
        this.swap(i, parentIdx);
        i = parentIdx;
      } else {
        break;
      }
    }
  }

  private heapifyDown(i: number): void {
    const size = this.heap.length;

    while (true) {
      let smallest = i;
      const left = this.leftChild(i);
      const right = this.rightChild(i);

      const current = this.heap[smallest];
      const leftItem = this.heap[left];
      const rightItem = this.heap[right];

      if (left < size && leftItem && current && leftItem.priority < current.priority) {
        smallest = left;
      }

      const smallestItem = this.heap[smallest];
      if (right < size && rightItem && smallestItem && rightItem.priority < smallestItem.priority) {
        smallest = right;
      }

      if (smallest !== i) {
        this.swap(i, smallest);
        i = smallest;
      } else {
        break;
      }
    }
  }

  /**
   * Add or update an item in the queue.
   * If the item already exists, it will be updated with the new priority.
   */
  push(item: QueueItem): void {
    const key = this.getKey(item.address, item.controllerAddress);
    const existingIndex = this.itemMap.get(key);

    if (existingIndex !== undefined) {
      // Update existing item
      const existing = this.heap[existingIndex];
      if (existing) {
        const oldPriority = existing.priority;
        existing.priority = item.priority;

        // Re-heapify based on priority change direction
        if (item.priority < oldPriority) {
          this.heapifyUp(existingIndex);
        } else {
          this.heapifyDown(existingIndex);
        }
      }
    } else {
      // Add new item
      this.heap.push(item);
      const newIndex = this.heap.length - 1;
      this.itemMap.set(key, newIndex);
      this.heapifyUp(newIndex);
    }
  }

  /**
   * Remove and return the item with the lowest priority.
   */
  pop(): QueueItem | undefined {
    if (this.heap.length === 0) {
      return undefined;
    }

    const min = this.heap[0];
    const last = this.heap.pop();

    if (min) {
      const key = this.getKey(min.address, min.controllerAddress);
      this.itemMap.delete(key);
    }

    if (this.heap.length > 0 && last) {
      this.heap[0] = last;
      const lastKey = this.getKey(last.address, last.controllerAddress);
      this.itemMap.set(lastKey, 0);
      this.heapifyDown(0);
    }

    return min;
  }

  /**
   * Return the item with the lowest priority without removing it.
   */
  peek(): QueueItem | undefined {
    return this.heap[0];
  }

  /**
   * Check if an item exists in the queue.
   */
  has(address: Address, controllerAddress: Address): boolean {
    const key = this.getKey(address, controllerAddress);
    return this.itemMap.has(key);
  }

  /**
   * Get an item from the queue without removing it.
   */
  get(address: Address, controllerAddress: Address): QueueItem | undefined {
    const key = this.getKey(address, controllerAddress);
    const index = this.itemMap.get(key);
    if (index !== undefined) {
      return this.heap[index];
    }
    return undefined;
  }

  /**
   * Remove an item from the queue.
   */
  remove(address: Address, controllerAddress: Address): boolean {
    const key = this.getKey(address, controllerAddress);
    const index = this.itemMap.get(key);

    if (index === undefined) {
      return false;
    }

    // Move item to top by giving it the lowest priority
    const item = this.heap[index];
    if (item) {
      item.priority = Number.MIN_SAFE_INTEGER;
      this.heapifyUp(index);
    }

    // Remove from top
    this.pop();
    return true;
  }

  /**
   * Get the number of items in the queue.
   */
  size(): number {
    return this.heap.length;
  }

  /**
   * Check if the queue is empty.
   */
  isEmpty(): boolean {
    return this.heap.length === 0;
  }

  /**
   * Clear all items from the queue.
   */
  clear(): void {
    this.heap = [];
    this.itemMap.clear();
  }

  /**
   * Get all items as an array (for debugging/serialization).
   */
  toArray(): QueueItem[] {
    return [...this.heap];
  }

  /**
   * Rebuild the queue from an array of items.
   */
  fromArray(items: QueueItem[]): void {
    this.clear();
    for (const item of items) {
      this.push(item);
    }
  }

  /**
   * Get all items that are due (priority <= current time).
   */
  getDueItems(currentTime: number): QueueItem[] {
    const dueItems: QueueItem[] = [];

    while (this.heap.length > 0) {
      const item = this.peek();
      if (item && item.priority <= currentTime) {
        const popped = this.pop();
        if (popped) {
          dueItems.push(popped);
        }
      } else {
        break;
      }
    }

    return dueItems;
  }
}
