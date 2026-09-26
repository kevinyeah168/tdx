/** Small in-memory LRU for immutable API payloads (historical dates). */
export class LruCache<K, V> {
  private readonly maxSize: number
  private readonly map = new Map<K, V>()

  constructor(maxSize = 16) {
    this.maxSize = Math.max(1, maxSize)
  }

  get(key: K): V | undefined {
    const value = this.map.get(key)
    if (value === undefined) return undefined
    this.map.delete(key)
    this.map.set(key, value)
    return value
  }

  set(key: K, value: V): void {
    if (this.map.has(key)) this.map.delete(key)
    this.map.set(key, value)
    while (this.map.size > this.maxSize) {
      const oldest = this.map.keys().next().value as K
      this.map.delete(oldest)
    }
  }

  clear(): void {
    this.map.clear()
  }
}
