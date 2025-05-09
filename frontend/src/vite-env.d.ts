/// <reference types="vite/client" />

interface ImportMeta {
  readonly env: Record<string, string>;
}

declare module 'react' {
  export * from 'react/index';
}

declare module 'lucide-react' {
  export * from 'lucide-react/dist/esm/index';
}

declare module 'recharts' {
  export * from 'recharts/index';
}
