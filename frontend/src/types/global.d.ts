

declare global {
  namespace JSX {
    interface IntrinsicElements {
      [elemName: string]: any;
    }
  }
}

declare module 'react' {
  export function useState<T>(initialState: T | (() => T)): [T, (newState: T | ((prevState: T) => T)) => void];
  export function useEffect(effect: () => void | (() => void), deps?: readonly any[]): void;
  export function useMemo<T>(factory: () => T, deps: readonly any[] | undefined): T;
  
  export const StrictMode: any;
  export function forwardRef<T, P = {}>(render: (props: P, ref: any) => any): any;
  export function createContext<T>(defaultValue: T): any;
  export function useContext<T>(context: any): T;
  
  export type ReactNode = any;
  export type ReactElement<T = any> = any;
  export type ElementRef<T = any> = any;
  export type ComponentPropsWithoutRef<T = any> = any;
  export type ComponentProps<T = any> = any;
  export type HTMLAttributes<T = any> = any;
  export type ThHTMLAttributes<T = any> = any;
  export type TdHTMLAttributes<T = any> = any;
  export type CSSProperties = any;
  export type Ref<T> = any;
  export type Context<T> = any;
}

declare module 'recharts' {
  export const LineChart: any;
  export const Line: any;
  export const XAxis: any;
  export const YAxis: any;
  export const CartesianGrid: any;
  export const Tooltip: any;
  export const Legend: any;
  export const ResponsiveContainer: any;
  export const BarChart: any;
  export const Bar: any;
}

declare module 'lucide-react' {
  export const AlertCircle: any;
  export const RefreshCw: any;
  export const Play: any;
  export const Square: any;
  export const X: any;
}

export {};
