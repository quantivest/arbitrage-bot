

declare global {
  namespace JSX {
    interface IntrinsicElements {
      [elemName: string]: any;
    }
  }
}

declare module 'react' {
  export const useState: any;
  export const useEffect: any;
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
}

export {};
