import { useState, useEffect, useMemo } from "react";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "./ui/card";
import { Slider } from "./ui/slider";
import { Label } from "./ui/label";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
import { ArbitrageTrade, TestModeSettings, AlertMessage, FailsafeStatusData, TestSimulationStatusPayload } from "../types";
import { AlertCircle, Play, StopCircle, CheckCircle, Zap, Info, Settings, BarChartHorizontalBig } from "lucide-react"; // Removed PercentSquare as it's not used
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { ScrollArea } from "./ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
import { formatDistanceToNow } from "date-fns";
import { Badge } from "./ui/badge";

// Persist settings in localStorage
const STORAGE_KEY_USDT_CAPITAL = "testMode_usdtCapital_v3";
const STORAGE_KEY_ASSET_CAPITAL_USD = "testMode_assetCapitalUSD_v3";
const STORAGE_KEY_BUFFER_PERCENTAGE = "testMode_bufferPercentage_v3";
const STORAGE_KEY_SELECTED_EXCHANGES = "testMode_selectedExchanges_v3";

const TARGET_TRADING_PAIRS = [
  "BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "XRP/USDT",
  "LTC/USDT", "DOT/USDT", "LINK/USDT", "BNB/USDT", "DOGE/USDT"
];

interface TestModeTabProps {
  testSimulationStatus: TestSimulationStatusPayload | null;
  supportedExchanges: string[];
  testTrades: ArbitrageTrade[];
  onBotAction: (action: "start_test" | "stop", settings?: TestModeSettings) => Promise<void>;
  alerts: AlertMessage[];
  failsafeStatus: FailsafeStatusData | null;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-700/80 backdrop-blur-sm p-3 rounded-md border border-gray-600 shadow-lg">
        <p className="label text-sm text-gray-300">{`Time: ${label}`}</p>
        {payload.map((pld: any, index: number) => (
          <p key={index} style={{ color: pld.color }} className="text-sm">
            {`${pld.name}: ${pld.dataKey === "profit_percentage" ? (pld.value ?? 0).toFixed(4) + "%" : pld.dataKey === "profit_quote" ? "$" + (pld.value ?? 0).toFixed(2) : (pld.value ?? "N/A")}`}
          </p>
        ))}
      </div>
    );
  }
  return null;
};

export default function TestModeTab({
  testSimulationStatus,
  supportedExchanges,
  testTrades,
  onBotAction,
  alerts,
  failsafeStatus,
}: TestModeTabProps) {
  const [usdtCapitalPerExchange, setUsdtCapitalPerExchange] = useState<number>(1000);
  const [assetCapitalUsdPerPair, setAssetCapitalUsdPerPair] = useState<number>(100);
  const [bufferPercentage, setBufferPercentage] = useState<number>(0.01);
  const [selectedExchanges, setSelectedExchanges] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const isSimulationRunning = testSimulationStatus?.status === "RUNNING" || testSimulationStatus?.status === "STARTING";
  const isSimulationStopping = testSimulationStatus?.status === "STOPPING";

  // Defensive copies of array props, ensuring they are always arrays.
  const currentSupportedExchanges = useMemo(() => Array.isArray(supportedExchanges) ? supportedExchanges : [], [supportedExchanges]);
  const currentTestTrades = useMemo(() => Array.isArray(testTrades) ? testTrades : [], [testTrades]);
  const currentAlerts = useMemo(() => Array.isArray(alerts) ? alerts : [], [alerts]);

  useEffect(() => {
    const savedUsdt = localStorage.getItem(STORAGE_KEY_USDT_CAPITAL);
    const savedAssetUsd = localStorage.getItem(STORAGE_KEY_ASSET_CAPITAL_USD);
    const savedBuffer = localStorage.getItem(STORAGE_KEY_BUFFER_PERCENTAGE);
    const savedExchangesStr = localStorage.getItem(STORAGE_KEY_SELECTED_EXCHANGES);

    if (savedUsdt) setUsdtCapitalPerExchange(Number(savedUsdt));
    if (savedAssetUsd) setAssetCapitalUsdPerPair(Number(savedAssetUsd));
    if (savedBuffer) setBufferPercentage(Number(savedBuffer));
    
    let initialSelection: string[] = [];
    if (savedExchangesStr) {
      try {
        const parsed = JSON.parse(savedExchangesStr);
        if (Array.isArray(parsed)) {
            initialSelection = parsed.filter(ex => currentSupportedExchanges.includes(ex));
        }
      } catch {
        // JSON parse error, ignore saved, initialSelection remains empty
      }
    }

    if (initialSelection.length >= 2) {
        setSelectedExchanges(initialSelection);
    } else if (currentSupportedExchanges.length >= 2) {
        setSelectedExchanges(currentSupportedExchanges.slice(0, 2));
    } else {
        setSelectedExchanges([]); // Fallback if not enough supported or saved are invalid/insufficient
    }
  }, [currentSupportedExchanges]); // Depends only on currentSupportedExchanges for initialization logic


  const handleSliderChange = (value: number, setter: React.Dispatch<React.SetStateAction<number>>, key: string) => {
    setter(value);
    localStorage.setItem(key, value.toString());
  };

  const handleExchangeToggle = (exchange: string) => {
    if (isSimulationRunning || isSimulationStopping) return;
    const newSelection = selectedExchanges.includes(exchange)
      ? selectedExchanges.filter((e) => e !== exchange)
      : [...selectedExchanges, exchange];
    setSelectedExchanges(newSelection);
    localStorage.setItem(STORAGE_KEY_SELECTED_EXCHANGES, JSON.stringify(newSelection));
  };

  const handleStartStopSimulation = async () => {
    setError(null);
    if (isSimulationRunning) {
      await onBotAction("stop");
    } else {
      if (selectedExchanges.length < 2) {
        setError("Please select at least 2 exchanges for testing.");
        return;
      }
      const settings: TestModeSettings = {
        usdt_capital_per_exchange: usdtCapitalPerExchange,
        asset_capital_usd_per_pair: assetCapitalUsdPerPair,
        buffer_percentage: bufferPercentage,
        exchanges: selectedExchanges,
      };
      await onBotAction("start_test", settings);
    }
  };

  const chartData = useMemo(() => {
    return currentTestTrades
      .slice(0, 50) 
      .map((trade) => ({
        time: trade.timestamp ? new Date(trade.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "N/A",
        profit_quote: parseFloat((trade.profit_quote ?? 0).toFixed(2)),
        profit_percentage: parseFloat((trade.profit_percentage ?? 0).toFixed(4)),
      }))
      .reverse(); 
  }, [currentTestTrades]);

  const summaryStats = useMemo(() => {
    const totalTrades = currentTestTrades.length;
    const totalProfit = currentTestTrades.reduce((sum, trade) => sum + (trade.profit_quote ?? 0), 0);
    const avgProfitPercentage = totalTrades > 0
        ? currentTestTrades.reduce((sum, trade) => sum + (trade.profit_percentage ?? 0), 0) / totalTrades
        : 0;
    return { totalTrades, totalProfit, avgProfitPercentage };
  }, [currentTestTrades]);
  
  const recentAlerts = useMemo(() => {
    return currentAlerts.filter(a => a?.message?.toLowerCase().includes("test") || a?.severity === "critical" || a?.severity === "error").slice(0,5);
  }, [currentAlerts]);

  return (
    <div className="space-y-6">
      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Configuration Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="bg-gray-800/50 border-gray-700">
        <CardContent className="pt-6">
            <div className={`p-4 rounded-md flex items-center justify-between ${isSimulationRunning ? "bg-green-700/30 border-green-500" : (testSimulationStatus?.status === "STOPPED" || testSimulationStatus?.status === "IDLE" || !testSimulationStatus?.status) ? "bg-gray-700/30 border-gray-500" : "bg-red-700/30 border-red-500"} border`}>
                <div className="flex items-center">
                    {isSimulationRunning ? <Zap className="h-5 w-5 text-green-400 mr-2 animate-pulse" /> : (testSimulationStatus?.status === "STOPPED" || testSimulationStatus?.status === "IDLE" || !testSimulationStatus?.status) ? <CheckCircle className="h-5 w-5 text-gray-400 mr-2" /> : <AlertCircle className="h-5 w-5 text-red-400 mr-2" />}
                    <span className={`text-lg font-medium ${isSimulationRunning ? "text-green-300" : (testSimulationStatus?.status === "STOPPED" || testSimulationStatus?.status === "IDLE" || !testSimulationStatus?.status) ? "text-gray-300" : "text-red-300"}`}>
                        Test Simulation: {testSimulationStatus?.status ? testSimulationStatus.status.replace(/_/g, " ") : "IDLE"}
                    </span>
                </div>
                {testSimulationStatus?.message && <p className="text-xs text-gray-400 ml-4 flex-shrink truncate" title={testSimulationStatus.message}>{testSimulationStatus.message}</p>}
                {isSimulationRunning && testSimulationStatus?.active_since && (
                    <p className="text-xs text-green-400 ml-auto whitespace-nowrap">Active since: {new Date(testSimulationStatus.active_since).toLocaleTimeString()}</p>
                )}
            </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-1 bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white flex items-center"><Settings size={20} className="mr-2 text-orange-400"/>Test Simulation Settings</CardTitle>
            <CardDescription className="text-gray-400">
              Configure parameters for the test simulation. The bot will use the 10 specified pairs: {TARGET_TRADING_PAIRS.map(p=>p.split("/")[0]).join(", ")}.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div>
              <Label htmlFor="usdtCapital" className="text-gray-300 flex justify-between">
                <span>USDT Capital (per Exchange)</span>
                <span className="text-orange-400 font-medium">${usdtCapitalPerExchange.toLocaleString()}</span>
              </Label>
              <Slider
                id="usdtCapital"
                value={[usdtCapitalPerExchange]}
                min={100} max={10000} step={100}
                onValueChange={(val) => handleSliderChange(val[0], setUsdtCapitalPerExchange, STORAGE_KEY_USDT_CAPITAL)}
                disabled={isSimulationRunning || isSimulationStopping}
                className="mt-2 [&>span:first-child]:h-1 [&>span:first-child>span]:bg-orange-500"
              />
            </div>
            <div>
              <Label htmlFor="assetCapitalUsd" className="text-gray-300 flex justify-between">
                <span>Asset Capital (USD per Pair, per Exchange)</span>
                <span className="text-orange-400 font-medium">${assetCapitalUsdPerPair.toLocaleString()}</span>
              </Label>
              <Slider
                id="assetCapitalUsd"
                value={[assetCapitalUsdPerPair]}
                min={10} max={1000} step={10}
                onValueChange={(val) => handleSliderChange(val[0], setAssetCapitalUsdPerPair, STORAGE_KEY_ASSET_CAPITAL_USD)}
                disabled={isSimulationRunning || isSimulationStopping}
                className="mt-2 [&>span:first-child]:h-1 [&>span:first-child>span]:bg-orange-500"
              />
               <p className="text-xs text-gray-500 mt-1">E.g., for BTC/USDT, this means ${assetCapitalUsdPerPair} worth of BTC per exchange.</p>
            </div>
            <div>
              <Label htmlFor="bufferPercentage" className="text-gray-300 flex justify-between">
                <span>Buffer Percentage</span>
                <span className="text-orange-400 font-medium">{bufferPercentage.toFixed(4)}%</span>
              </Label>
              <Slider
                id="bufferPercentage"
                value={[bufferPercentage]}
                min={0.0000} max={1.0000} step={0.0001} 
                onValueChange={(val) => handleSliderChange(val[0], setBufferPercentage, STORAGE_KEY_BUFFER_PERCENTAGE)}
                disabled={isSimulationRunning || isSimulationStopping}
                className="mt-2 [&>span:first-child]:h-1 [&>span:first-child>span]:bg-orange-500"
              />
            </div>
            <div>
              <Label className="text-gray-300 mb-2 block">Select Exchanges (Min. 2)</Label>
              <div className="grid grid-cols-2 gap-2">
                {currentSupportedExchanges.map((exchange) => (
                  <Button
                    key={exchange}
                    variant={selectedExchanges.includes(exchange) ? "default" : "outline"}
                    onClick={() => handleExchangeToggle(exchange)}
                    disabled={isSimulationRunning || isSimulationStopping}
                    className={`w-full text-sm ${selectedExchanges.includes(exchange) ? "bg-orange-500 hover:bg-orange-600 text-white" : "border-gray-600 bg-gray-700 hover:bg-gray-600 text-gray-300"}`}
                  >
                    {exchange.charAt(0).toUpperCase() + exchange.slice(1)}
                  </Button>
                ))}
              </div>
            </div>
          </CardContent>
          <CardFooter>
            <Button
              onClick={handleStartStopSimulation}
              disabled={(selectedExchanges.length < 2 && !isSimulationRunning) || isSimulationStopping}
              className={`w-full text-white font-semibold py-3 px-4 rounded-md transition-colors duration-150 flex items-center justify-center space-x-2 ${isSimulationRunning ? (isSimulationStopping ? "bg-yellow-600 hover:bg-yellow-700 cursor-not-allowed" : "bg-red-600 hover:bg-red-700") : "bg-green-600 hover:bg-green-700"}`}
            >
              {isSimulationRunning ? (isSimulationStopping ? <StopCircle size={20} className="animate-spin"/> : <StopCircle size={20}/>) : <Play size={20}/>}
              <span>{isSimulationRunning ? (isSimulationStopping ? "Stopping..." : "Stop Simulation") : "Start Simulation"}</span>
            </Button>
          </CardFooter>
        </Card>

        <Card className="lg:col-span-2 bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white flex items-center"><BarChartHorizontalBig size={20} className="mr-2 text-orange-400"/>Simulation Results</CardTitle>
            <CardDescription className="text-gray-400">
              Performance metrics and trade history from the current or last test simulation.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
              <div className="p-4 bg-gray-700/50 rounded-lg text-center">
                <p className="text-xs text-gray-400 uppercase">Total Test Trades</p>
                <p className="text-2xl font-bold text-white">{testSimulationStatus?.total_test_trades ?? summaryStats.totalTrades}</p>
              </div>
              <div className="p-4 bg-gray-700/50 rounded-lg text-center">
                <p className="text-xs text-gray-400 uppercase">Total Test Profit (USDT)</p>
                <p className={`text-2xl font-bold ${(testSimulationStatus?.total_test_profit ?? summaryStats.totalProfit) >= 0 ? "text-green-400" : "text-red-400"}`}>
                  ${(testSimulationStatus?.total_test_profit ?? summaryStats.totalProfit).toFixed(2)}
                </p>
              </div>
              <div className="p-4 bg-gray-700/50 rounded-lg text-center">
                <p className="text-xs text-gray-400 uppercase">Avg. Profit %</p>
                <p className={`text-2xl font-bold ${(summaryStats.avgProfitPercentage ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {(summaryStats.avgProfitPercentage ?? 0).toFixed(4)}%
                </p>
              </div>
            </div>

            <div className="h-[250px] mb-6">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                  <XAxis dataKey="time" stroke="#9ca3af" fontSize={12} />
                  <YAxis yAxisId="left" stroke="#82ca9d" fontSize={12} domain={['auto', 'auto']} />
                  <YAxis yAxisId="right" orientation="right" stroke="#ffc658" fontSize={12} domain={['auto', 'auto']} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: "12px" }} />
                  <Line yAxisId="left" type="monotone" dataKey="profit_quote" stroke="#82ca9d" strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 5 }} name="Profit (USDT)" />
                  <Line yAxisId="right" type="monotone" dataKey="profit_percentage" stroke="#ffc658" strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 5 }} name="Profit (%)" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            
            <h3 className="text-lg font-semibold text-white mb-2 flex items-center"><Info size={18} className="mr-2 text-orange-400"/>Recent Test Trades (Max 50)</h3>
            <ScrollArea className="h-[200px] border border-gray-700 rounded-md">
              <Table>
                <TableHeader>
                  <TableRow className="bg-gray-750">
                    <TableHead className="text-gray-400">Time</TableHead>
                    <TableHead className="text-gray-400">Pair</TableHead>
                    <TableHead className="text-gray-400">Type</TableHead>
                    <TableHead className="text-gray-400">Exchanges</TableHead>
                    <TableHead className="text-right text-gray-400">Profit (USDT)</TableHead>
                    <TableHead className="text-right text-gray-400">Profit (%)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {currentTestTrades.length > 0 ? (
                    currentTestTrades.map((trade, index) => (
                      <TableRow key={trade.id ?? `trade-${index}`} className="hover:bg-gray-700/50 text-xs border-b border-gray-700 last:border-b-0">
                        <TableCell className="py-2 text-gray-300">{trade.timestamp ? formatDistanceToNow(new Date(trade.timestamp), { addSuffix: true }) : "N/A"}</TableCell>
                        <TableCell className="py-2 text-gray-300">{trade.pair ?? "N/A"}</TableCell>
                        <TableCell className="py-2 text-gray-300">
                          <Badge variant={trade.type === "buy-sell-buy" ? "default" : "secondary"} className="whitespace-nowrap">{trade.type ?? "N/A"}</Badge>
                        </TableCell>
                        <TableCell className="py-2 text-gray-300">{`${trade.buy_exchange ?? "N/A"} → ${trade.sell_exchange ?? "N/A"}`}</TableCell>
                        <TableCell className={`py-2 text-right font-medium ${(trade.profit_quote ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                          ${(trade.profit_quote ?? 0).toFixed(2)}
                        </TableCell>
                        <TableCell className={`py-2 text-right font-medium ${(trade.profit_percentage ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {(trade.profit_percentage ?? 0).toFixed(4)}%
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow><TableCell colSpan={6} className="text-center text-gray-500 py-4">No test trades recorded yet.</TableCell></TableRow>
                  )}
                </TableBody>
              </Table>
            </ScrollArea>

            {recentAlerts.length > 0 && (
                <div className="mt-6">
                    <h3 className="text-lg font-semibold text-white mb-2 flex items-center"><AlertCircle size={18} className="mr-2 text-orange-400"/>Recent Test-Related Alerts</h3>
                    <ScrollArea className="h-[150px] space-y-2 border border-gray-700 rounded-md p-2">
                        {recentAlerts.map((alert, index) => (
                            <Alert key={alert.id ?? `alert-${index}`} variant={alert.severity === "error" || alert.severity === "critical" ? "destructive" : "default"} className="mb-2 last:mb-0 bg-gray-700/70 border-gray-600">
                                <AlertCircle className={`h-4 w-4 ${alert.severity === "error" || alert.severity === "critical" ? "text-red-400" : "text-yellow-400"}`} />
                                <AlertTitle className={`text-sm font-medium ${alert.severity === "error" || alert.severity === "critical" ? "text-red-300" : "text-yellow-300"}`}>{alert.severity?.toUpperCase() ?? "INFO"}</AlertTitle>
                                <AlertDescription className="text-xs text-gray-400">{alert.message ?? "No message"}</AlertDescription>
                            </Alert>
                        ))}
                    </ScrollArea>
                </div>
            )}

            {failsafeStatus && failsafeStatus.active && (
                <Alert variant="warning" className="mt-6 bg-yellow-700/20 border-yellow-500">
                    <Zap className="h-5 w-5 text-yellow-400" />
                    <AlertTitle className="text-yellow-300">Failsafe Active!</AlertTitle>
                    <AlertDescription className="text-yellow-400 text-xs">
                        {failsafeStatus.reason || "Trading is temporarily paused due to failsafe conditions."}
                        {failsafeStatus.details && <span className="block mt-1">Details: {typeof failsafeStatus.details === 'string' ? failsafeStatus.details : JSON.stringify(failsafeStatus.details)}</span>}
                    </AlertDescription>
                </Alert>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

