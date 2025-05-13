import React, { useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "./ui/card";
import { ArbitrageTrade, ExchangeBalance, AlertMessage, FailsafeStatusData } from "../types";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { formatDistanceToNow } from "date-fns";
import { Button } from "./ui/button";
import { AlertCircle, RefreshCw, ShieldAlert, ShieldCheck, TrendingUp, TrendingDown, ListChecks, Info, ExternalLink, AlertTriangle } from "lucide-react"; // MODIFICATION: Added AlertTriangle
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
import { ScrollArea } from "./ui/scroll-area";
import { Badge } from "./ui/badge";

interface DashboardTabProps {
  liveTrades: ArbitrageTrade[];
  testTrades: ArbitrageTrade[];
  balances: ExchangeBalance[];
  isTestMode: boolean;
  isRunning: boolean;
  alerts: AlertMessage[];
  failsafeStatus: FailsafeStatusData | null;
  onReactivateFailsafe: (type: "pair" | "exchange" | "global", entity_name?: string) => Promise<void>;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-700/80 backdrop-blur-sm p-3 rounded-md border border-gray-600 shadow-lg">
        <p className="label text-sm text-gray-300">{`Time: ${label}`}</p>
        {payload.map((pld: any, index: number) => (
          <p key={index} style={{ color: pld.color }} className="text-sm">
            {`${pld.name}: ${pld.dataKey === "profit_percentage" || pld.dataKey === "spread_percentage" ? pld.value.toFixed(4) + "%" : pld.dataKey === "profit_quote" ? "$" + pld.value.toFixed(2) : pld.value}`}
          </p>
        ))}
      </div>
    );
  }
  return null;
};

export default function DashboardTab({
  liveTrades,
  testTrades,
  balances,
  isTestMode,
  isRunning,
  alerts,
  failsafeStatus,
  onReactivateFailsafe,
}: DashboardTabProps) {
  const tradesToDisplay = isTestMode ? testTrades : liveTrades;

  const chartData = useMemo(() => {
    return tradesToDisplay
      .slice(0, 50) // Display last 50 trades for performance
      .map((trade) => ({
        time: new Date(trade.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        profit_quote: parseFloat(trade.profit_quote.toFixed(2)),
        profit_percentage: parseFloat(trade.profit_percentage.toFixed(4)),
      }))
      .reverse(); // Reverse to show oldest first in chart
  }, [tradesToDisplay]);

  const summaryStats = useMemo(() => {
    const totalTrades = tradesToDisplay.length;
    const totalProfit = tradesToDisplay.reduce((sum, trade) => sum + trade.profit_quote, 0);
    const totalVolumeQuote = tradesToDisplay.reduce((sum, trade) => sum + (trade.buy_trade.price * trade.buy_trade.amount), 0);
    const avgProfitPerTrade = totalTrades > 0 ? totalProfit / totalTrades : 0;
    const avgProfitPercentage = totalTrades > 0
        ? tradesToDisplay.reduce((sum, trade) => sum + trade.profit_percentage, 0) / totalTrades
        : 0;
    const winningTrades = tradesToDisplay.filter(t => t.profit_quote > 0).length;
    const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;

    return {
      totalTrades,
      totalProfit,
      totalVolumeQuote,
      avgProfitPerTrade,
      avgProfitPercentage,
      winRate,
    };
  }, [tradesToDisplay]);

  const recentAlerts = useMemo(() => {
    return alerts.slice(0, 10); // Show last 10 alerts
  }, [alerts]);

  const getAlertIcon = (severity: string) => {
    switch (severity) {
      case "critical":
        return <AlertCircle className="h-4 w-4 mr-2 text-red-400 flex-shrink-0" />;
      case "error":
        return <AlertCircle className="h-4 w-4 mr-2 text-red-500 flex-shrink-0" />;
      case "warning":
        return <AlertTriangle className="h-4 w-4 mr-2 text-yellow-400 flex-shrink-0" />; // MODIFICATION: Changed icon for warning
      case "info":
      default:
        return <Info className="h-4 w-4 mr-2 text-blue-400 flex-shrink-0" />;
    }
  };

  const getAlertBgColor = (severity: string) => {
    switch (severity) {
      case "critical": return "bg-red-800/30 border-red-600";
      case "error": return "bg-red-700/30 border-red-500";
      case "warning": return "bg-yellow-700/30 border-yellow-500";
      case "info":
      default: return "bg-blue-700/30 border-blue-500";
    }
  };

  return (
    <div className="space-y-6 pb-6">
      <div className="flex flex-col sm:flex-row justify-between items-center mb-2">
        <h2 className="text-3xl font-bold tracking-tight text-white">
          {isTestMode ? "Test Mode Stats" : "Live Trading Stats"}
        </h2>
        <Badge variant={isRunning && (isTestMode || !failsafeStatus?.global_trading_halt) ? "success" : "destructive"} className="mt-2 sm:mt-0 text-sm px-3 py-1">
          {isRunning && (isTestMode || !failsafeStatus?.global_trading_halt) ? 
            (isTestMode ? "Test Simulation Running" : "Live Bot Active") :
            (isTestMode ? "Test Simulation Stopped" : "Live Bot Stopped")
          }
          {failsafeStatus?.global_trading_halt && !isTestMode && " (Global Halt Active)"}
        </Badge>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <Card className="bg-gray-800/50 border-gray-700 shadow-md hover:shadow-lg transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-gray-300">Total Trades</CardTitle>
            <ListChecks className="h-4 w-4 text-gray-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">{summaryStats.totalTrades}</div>
            <p className="text-xs text-gray-400">Win Rate: {summaryStats.winRate.toFixed(1)}%</p>
          </CardContent>
        </Card>
        <Card className="bg-gray-800/50 border-gray-700 shadow-md hover:shadow-lg transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-gray-300">Total Profit (USDT)</CardTitle>
            {summaryStats.totalProfit >= 0 ? <TrendingUp className="h-4 w-4 text-green-500" /> : <TrendingDown className="h-4 w-4 text-red-500" />}
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${summaryStats.totalProfit >= 0 ? "text-green-400" : "text-red-400"}`}>
              ${summaryStats.totalProfit.toFixed(2)}
            </div>
            <p className="text-xs text-gray-400">Avg. Profit/Trade: ${summaryStats.avgProfitPerTrade.toFixed(2)}</p>
          </CardContent>
        </Card>
        <Card className="bg-gray-800/50 border-gray-700 shadow-md hover:shadow-lg transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-gray-300">Avg. Profit %</CardTitle>
            <Info className="h-4 w-4 text-gray-500" />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${summaryStats.avgProfitPercentage >= 0 ? "text-green-400" : "text-red-400"}`}>
              {summaryStats.avgProfitPercentage.toFixed(4)}%
            </div>
            <p className="text-xs text-gray-400">Total Volume (USDT): ${summaryStats.totalVolumeQuote.toFixed(2)}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-gray-800/50 border-gray-700 shadow-md">
          <CardHeader>
            <CardTitle className="text-white">Profit Over Time (Last 50 Trades)</CardTitle>
          </CardHeader>
          <CardContent className="h-[300px] pt-4">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#4b5563" strokeOpacity={0.5} />
                <XAxis dataKey="time" stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `$${value}`} />
                <Tooltip content={<CustomTooltip />} />
                <Legend wrapperStyle={{fontSize: "12px", color: "#d1d5db"}} />
                <Line type="monotone" dataKey="profit_quote" stroke="#34d399" strokeWidth={2} dot={{ r: 2, fill: "#34d399" }} activeDot={{ r: 6, stroke: "#10b981", fill: "#10b981" }} name="Profit (USDT)"/>
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card className="bg-gray-800/50 border-gray-700 shadow-md">
          <CardHeader>
            <CardTitle className="text-white">Profit % Over Time (Last 50 Trades)</CardTitle>
          </CardHeader>
          <CardContent className="h-[300px] pt-4">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#4b5563" strokeOpacity={0.5} />
                <XAxis dataKey="time" stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `${value.toFixed(4)}%`} domain={["auto", "auto"]} />
                <Tooltip content={<CustomTooltip />} />
                <Legend wrapperStyle={{fontSize: "12px", color: "#d1d5db"}}/>
                <Line type="monotone" dataKey="profit_percentage" stroke="#fb923c" strokeWidth={2} dot={{ r: 2, fill: "#fb923c" }} activeDot={{ r: 6, stroke: "#f97316", fill: "#f97316" }} name="Profit %" />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card className="bg-gray-800/50 border-gray-700 shadow-md">
          <CardHeader>
            <CardTitle className="text-white">Recent Trades</CardTitle>
            <CardDescription className="text-gray-400">Last 10 executed trades.</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[300px]">
              <Table>
                <TableHeader>
                  <TableRow className="border-gray-700 hover:bg-gray-700/30">
                    <TableHead className="text-gray-300">Time</TableHead>
                    <TableHead className="text-gray-300">Pair</TableHead>
                    <TableHead className="text-gray-300">Buy Ex</TableHead>
                    <TableHead className="text-gray-300">Sell Ex</TableHead>
                    <TableHead className="text-right text-gray-300">Profit %</TableHead>
                    <TableHead className="text-right text-gray-300">Profit (Q)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tradesToDisplay.slice(0, 10).map((trade) => (
                    <TableRow key={trade.id} className="border-gray-700 hover:bg-gray-700/50">
                      <TableCell className="text-xs text-gray-400">{new Date(trade.timestamp).toLocaleTimeString()}</TableCell>
                      <TableCell className="font-medium text-gray-200">{trade.symbol}</TableCell>
                      <TableCell className="text-gray-300">{trade.buy_trade.exchange}</TableCell>
                      <TableCell className="text-gray-300">{trade.sell_trade.exchange}</TableCell>
                      <TableCell className={`text-right font-medium ${trade.profit_percentage >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {trade.profit_percentage.toFixed(4)}%
                      </TableCell>
                      <TableCell className={`text-right font-medium ${trade.profit_quote >= 0 ? "text-green-400" : "text-red-400"}`}>
                        ${trade.profit_quote.toFixed(2)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {tradesToDisplay.length === 0 && (
                    <TableRow className="border-gray-700">
                      <TableCell colSpan={6} className="text-center text-gray-400 py-4 italic">No trades to display.</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </ScrollArea>
          </CardContent>
        </Card>

        <Card className="bg-gray-800/50 border-gray-700 shadow-md">
          <CardHeader>
            <CardTitle className="text-white">Exchange Balances (USDT)</CardTitle>
            <CardDescription className="text-gray-400">Available USDT balance per connected exchange.</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[300px]">
              <Table>
                <TableHeader>
                  <TableRow className="border-gray-700 hover:bg-gray-700/30">
                    <TableHead className="text-gray-300">Exchange</TableHead>
                    <TableHead className="text-right text-gray-300">USDT Balance</TableHead>
                    <TableHead className="text-right text-gray-300">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {balances.map((bal) => (
                    <TableRow key={bal.exchange} className="border-gray-700 hover:bg-gray-700/50">
                      <TableCell className="font-medium text-gray-200">{bal.exchange.charAt(0).toUpperCase() + bal.exchange.slice(1)}</TableCell>
                      <TableCell className="text-right text-gray-300">
                        {bal.error ? <span className="text-red-500">Error</span> : (bal.balances["USDT"]?.free ?? 0).toFixed(2)}
                      </TableCell>
                      <TableCell className="text-right">
                        {bal.error ? 
                          <Badge variant="destructive">Error</Badge> :
                          <Badge variant="success">OK</Badge>
                        }
                      </TableCell>
                    </TableRow>
                  ))}
                  {balances.length === 0 && (
                    <TableRow className="border-gray-700">
                      <TableCell colSpan={3} className="text-center text-gray-400 py-4 italic">No exchange balances to display.</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      <Card className="bg-gray-800/50 border-gray-700 shadow-md">
        <CardHeader>
          <CardTitle className="text-white">System Alerts & Failsafes</CardTitle>
          <CardDescription className="text-gray-400">
            Recent system notifications and status of automated failsafes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <h3 className="text-lg font-semibold text-gray-200 mb-2">Recent Alerts (Last 10)</h3>
              <ScrollArea className="h-[250px] pr-3">
                {recentAlerts.length > 0 ? (
                  <div className="space-y-2">
                    {recentAlerts.map((alert) => (
                      <div key={alert.id} className={`p-3 rounded-md border ${getAlertBgColor(alert.severity)}`}>
                        <div className="flex justify-between items-start mb-1">
                          <div className="flex items-center">
                            {getAlertIcon(alert.severity)}
                            <span className="text-sm font-medium text-gray-200">
                              {alert.type.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}
                              {alert.entity_name && ` (${alert.entity_name})`}
                            </span>
                          </div>
                          <span className="text-xs text-gray-500">
                            {formatDistanceToNow(new Date(alert.timestamp), { addSuffix: true })}
                          </span>
                        </div>
                        <p className="text-xs text-gray-300 leading-relaxed">{alert.message}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 italic">No recent alerts.</p>
                )}
              </ScrollArea>
            </div>
            <div>
              <h3 className="text-lg font-semibold text-gray-200 mb-2">Failsafe Status</h3>
              {failsafeStatus ? (
                <div className="space-y-3">
                  <div className={`p-3 rounded-md ${failsafeStatus.global_trading_halt ? "bg-red-800/30 border-red-600" : "bg-green-800/30 border-green-600"}`}>
                    <div className="flex items-center mb-1">
                      {failsafeStatus.global_trading_halt ? <ShieldAlert className="h-5 w-5 mr-2 text-red-400" /> : <ShieldCheck className="h-5 w-5 mr-2 text-green-400" />}
                      <span className="font-medium text-gray-200">Global Trading: {failsafeStatus.global_trading_halt ? "HALTED" : "Active"}</span>
                    </div>
                    {failsafeStatus.global_trading_halt && (
                      <>
                        <p className="text-xs text-gray-300">Reason: {failsafeStatus.global_halt_reason || "N/A"}</p>
                        <p className="text-xs text-gray-400">Halted since: {failsafeStatus.global_halt_timestamp ? formatDistanceToNow(new Date(failsafeStatus.global_halt_timestamp), { addSuffix: true }) : "N/A"}</p>
                        <Button size="sm" variant="destructive_outline" className="mt-2" onClick={() => onReactivateFailsafe("global")}>Reactivate Global Trading</Button>
                      </>
                    )}
                  </div>
                  <p className="text-xs text-gray-400">Historical High USDT Balance: ${failsafeStatus.historical_high_balance_usdt?.toFixed(2) ?? "0.00"}</p>
                  
                  {Object.keys(failsafeStatus.disabled_exchanges).length > 0 && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-300 mb-1">Disabled Exchanges:</h4>
                      <ul className="list-disc list-inside space-y-1 pl-2">
                        {Object.entries(failsafeStatus.disabled_exchanges).map(([ex, data]) => (
                          <li key={ex} className="text-xs text-red-400">
                            {ex.charAt(0).toUpperCase() + ex.slice(1)} (Reason: {data.reason}, Cooldown until: {data.cooldown_until ? formatDistanceToNow(new Date(data.cooldown_until), { addSuffix: true }) : "N/A"})
                            <Button size="xs" variant="outline" className="ml-2 py-0 px-1 h-5 text-xs" onClick={() => onReactivateFailsafe("exchange", ex)}>Reactivate</Button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {Object.keys(failsafeStatus.disabled_pairs).length > 0 && (
                     <div>
                      <h4 className="text-sm font-medium text-gray-300 mb-1">Disabled Pairs:</h4>
                      <ul className="list-disc list-inside space-y-1 pl-2">
                        {Object.entries(failsafeStatus.disabled_pairs).map(([pair, data]) => (
                          <li key={pair} className="text-xs text-yellow-400">
                            {pair} (Reason: {data.reason}, Cooldown until: {data.cooldown_until ? formatDistanceToNow(new Date(data.cooldown_until), { addSuffix: true }) : "N/A"})
                            <Button size="xs" variant="outline" className="ml-2 py-0 px-1 h-5 text-xs" onClick={() => onReactivateFailsafe("pair", pair)}>Reactivate</Button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {(Object.keys(failsafeStatus.disabled_exchanges).length === 0 && Object.keys(failsafeStatus.disabled_pairs).length === 0 && !failsafeStatus.global_trading_halt) && (
                    <p className="text-sm text-green-400 italic">All failsafes nominal.</p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-gray-400 italic">Failsafe status not available.</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

