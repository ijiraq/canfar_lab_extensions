declare module 'firefly-api-access' {
  export function initFirefly(url: string): () => Promise<any>;
}
