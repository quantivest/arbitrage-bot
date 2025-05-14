import { useState, useEffect, useMemo } from "react";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "./ui/card";
import { Slider } from "./ui/slider";
import { Label } from "./ui/label";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
import { ArbitrageTrade, TestModeSettings, AlertMessage, FailsafeStatusData, TestSimulationStatusPayload } from "../types";
import { AlertCircle, Play, StopCircle, CheckCircle, Zap, Info, Settings, BarChartHorizontalBig, PercentSquare } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { ScrollArea } from "./ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";
import { formatDistanceToNow } from "date-fns";
import { Badge } from "./ui/badge";

// Persist settings in localStorage
const STORAGE_KEY_USDT_CAPITAL = "testMode_usdtCapital_v3";
const STORAGE_KEY_ASSET_CAPITAL_USD = "testMode_assetCapitalUSD_v3"; // MODIFIED: Key for USD value
const STORAGE_KEY_BUFFER_PERCENTAGE = "testMode_bufferPercentage_v3";
const STORAGE_KEY_SELECTED_EXCHANGES = "testMode_selectedExchanges_v3";

// Defined trading pairs as per user request (for UI context, backend uses config)
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
            {`${pld.name}: ${pld.dataKey === "profit_percentage" ? pld.value.toFixed(4) + "%" : pld.dataKey === "profit_quote" ? "$" + pld.value.toFixed(2) : pld.value}`}
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
  const [assetCapitalUsdPerPair, setAssetCapitalUsdPerPair] = useState<number>(100); // MODIFIED: State for USD value, default to 100 USD
  const [bufferPercentage, setBufferPercentage] = useState<number>(0.01);
  const [selectedExchanges, setSelectedExchanges] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const isSimulationRunning = testSimulationStatus?.status === "RUNNING" || testSimulationStatus?.status === "STARTING";

  useEffect(() => {
    const savedUsdt = localStorage.getItem(STORAGE_KEY_USDT_CAPITAL);
    const savedAssetUsd = localStorage.getItem(STORAGE_KEY_ASSET_CAPITAL_USD); // MODIFIED: Use new key
    const savedBuffer = localStorage.getItem(STORAGE_KEY_BUFFER_PERCENTAGE);
    const savedExchanges = localStorage.getItem(STORAGE_KEY_SELECTED_EXCHANGES);

    if (savedUsdt) setUsdtCapitalPerExchange(Number(savedUsdt));
    if (savedAssetUsd) setAssetCapitalUsdPerPair(Number(savedAssetUsd)); // MODIFIED: Use new key and setter
    if (savedBuffer) setBufferPercentage(Number(savedBuffer));
    
    if (savedExchanges) {
      try {
        const parsed = JSON.parse(savedExchanges);
        if (Array.isArray(parsed)) {
            const validSavedExchanges = parsed.filter(ex => supportedExchanges.includes(ex));
            if (validSavedExchanges.length >= 2) {
                setSelectedExchanges(validSavedExchanges);
            } else if (supportedExchanges.length >=2) {
                setSelectedExchanges(supportedExchanges.slice(0, 2));
            }
        } else if (supportedExchanges.length >=2) {
            setSelectedExchanges(supportedExchanges.slice(0, 2));
        }
      } catch { 
        if (supportedExchanges.length >=2) {
            setSelectedExchanges(supportedExchanges.slice(0, 2));
        }
      }
    } else if (supportedExchanges.length >= 2 && selectedExchanges.length === 0) {
      setSelectedExchanges(supportedExchanges.slice(0, 2));
    }
  }, [supportedExchanges]);

  const handleSliderChange = (value: number, setter: React.Dispatch<React.SetStateAction<number>>, key: string) => {
    setter(value);
    localStorage.setItem(key, value.toString());
  };

  const handleExchangeToggle = (exchange: string) => {
    if (isSimulationRunning) return;
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
        asset_capital_usd_per_pair: assetCapitalUsdPerPair, // MODIFIED: Pass USD value
        buffer_percentage: bufferPercentage, // Backend expects actual percentage e.g. 0.01 for 0.01%
        exchanges: selectedExchanges,
      };
      await onBotAction("start_test", settings);
    }
  };

  const chartData = useMemo(() => {
    return testTrades
      .slice(0, 50) 
      .map((trade) => ({
        time: new Date(trade.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        profit_quote: parseFloat(trade.profit_quote.toFixed(2)),
        profit_percentage: parseFloat(trade.profit_percentage.toFixed(4)),
      }))
      .reverse(); 
  }, [testTrades]);

  const summaryStats = useMemo(() => {
    const totalTrades = testTrades.length;
    const totalProfit = testTrades.reduce((sum, trade) => sum + trade.profit_quote, 0);
    const avgProfitPercentage = totalTrades > 0
        ? testTrades.reduce((sum, trade) => sum + trade.profit_percentage, 0) / totalTrades
        : 0;
    return { totalTrades, totalProfit, avgProfitPercentage };
  }, [testTrades]);
  
  const recentAlerts = useMemo(() => {
    return alerts.filter(a => a.message.toLowerCase().includes("test") || a.severity === "critical" || a.severity === "error").slice(0,5);
  }, [alerts]);

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
            <div className={`p-4 rounded-md flex items-center justify-between ${isSimulationRunning ? "bg-green-700/30 border-green-500" : testSimulationStatus?.status === "STOPPED" || testSimulationStatus?.status === "IDLE" ? "bg-gray-700/30 border-gray-500" : "bg-red-700/30 border-red-500"} border`}>
                <div className="flex items-center">
                    {isSimulationRunning ? <Zap className="h-5 w-5 text-green-400 mr-2 animate-pulse" /> : (testSimulationStatus?.status === "STOPPED" || testSimulationStatus?.status === "IDLE") ? <CheckCircle className="h-5 w-5 text-gray-400 mr-2" /> : <AlertCircle className="h-5 w-5 text-red-400 mr-2" />}
                    <span className={`text-lg font-medium ${isSimulationRunning ? "text-green-300" : (testSimulationStatus?.status === "STOPPED" || testSimulationStatus?.status === "IDLE") ? "text-gray-300" : "text-red-300"}`}>
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
                disabled={isSimulationRunning}
                className="mt-2 [&>span:first-child]:h-1 [&>span:first-child>span]:bg-orange-500"
              />
            </div>
            <div>
              <Label htmlFor="assetCapitalUsd" className="text-gray-300 flex justify-between"> {/* MODIFIED: Label and htmlFor */}
                <span>Asset Capital (USD per Pair, per Exchange)</span> {/* MODIFIED: Label text */}
                <span className="text-orange-400 font-medium">${assetCapitalUsdPerPair.toLocaleString()}</span> {/* MODIFIED: Display USD value */}
              </Label>
              <Slider
                id="assetCapitalUsd" // MODIFIED: id
                value={[assetCapitalUsdPerPair]} // MODIFIED: Use USD state
                min={10} max={1000} step={10} // MODIFIED: Adjusted range for USD value (e.g., $10 to $1000)
                onValueChange={(val) => handleSliderChange(val[0], setAssetCapitalUsdPerPair, STORAGE_KEY_ASSET_CAPITAL_USD)} // MODIFIED: Use new key and setter
                disabled={isSimulationRunning}
                className="mt-2 [&>span:first-child]:h-1 [&>span:first-child>span]:bg-orange-500"
              />
               <p className="text-xs text-gray-500 mt-1">E.g., for BTC/USDT, this means ${assetCapitalUsdPerPair} worth of BTC per exchange.</p> {/* MODIFIED: Description */}
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
                disabled={isSimulationRunning}
                className="mt-2 [&>span:first-child]:h-1 [&>span:first-child>span]:bg-orange-500"
              />
            </div>
            <div>
              <Label className="text-gray-300 mb-2 block">Select Exchanges (Min. 2)</Label>
              <div className="grid grid-cols-2 gap-2">
                {supportedExchanges.map((exchange) => (
                  <Button
                    key={exchange}
                    variant={selectedExchanges.includes(exchange) ? "default" : "outline"}
                    onClick={() => handleExchangeToggle(exchange)}
                    disabled={isSimulationRunning}
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
              disabled={selectedExchanges.length < 2 && !isSimulationRunning}
              className={`w-full text-white font-semibold py-3 px-4 rounded-md transition-colors duration-150 flex items-center justify-center space-x-2 ${isSimulationRunning ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}`}
            >
              {isSimulationRunning ? <StopCircle size={20}/> : <Play size={20}/>}
              <span>{isSimulationRunning ? "Stop Simulation" : "Start Simulation"}</span>
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
                <p className={`text-2xl font-bold ${summaryStats.avgProfitPercentage >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {summaryStats.avgProfitPercentage.toFixed(4)}%
                </p>
              </div>
            </div>

            <div className="h-[250px] mb-6">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                  <XAxis dataKey="time" stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: "12px" }} />
                  <Line type="monotone" dataKey="profit_quote" name="Profit (USDT)" stroke="#34d399" strokeWidth={2} dot={{ r: 2, fill: "#34d399" }} activeDot={{ r: 4 }} />
                  <Line type="monotone" dataKey="profit_percentage" name="Profit (%)" stroke="#fb923c" strokeWidth={2} dot={{ r: 2, fill: "#fb923c" }} activeDot={{ r: 4 }} yAxisId="percentage" />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <ScrollArea className="h-[300px] border border-gray-700 rounded-md">
              <Table>
                <TableHeader className="sticky top-0 bg-gray-750 z-10">
                  <TableRow>
                    <TableHead className="text-gray-300">Time</TableHead>
                    <TableHead className="text-gray-300">Pair</TableHead>
                    <TableHead className="text-gray-300">Buy</TableHead>
                    <TableHead className="text-gray-300">Sell</TableHead>
                    <TableHead className="text-right text-gray-300">Profit ($)</TableHead>
                    <TableHead className="text-right text-gray-300">Profit (%)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {testTrades.length > 0 ? (
                    testTrades.map((trade) => (
                      <TableRow key={trade.id} className="hover:bg-gray-700/50">
                        <TableCell className="text-xs text-gray-400">{formatDistanceToNow(new Date(trade.timestamp), { addSuffix: true })}</TableCell>
                        <TableCell>{trade.symbol}</TableCell>
                        <TableCell>
                          <Badge variant="secondary" className="bg-green-700/50 text-green-300 border-green-600">
                            {trade.buy_trade.exchange} @ {trade.buy_trade.price.toFixed(trade.symbol.endsWith("USDT") ? 2 : 8)}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary" className="bg-red-700/50 text-red-300 border-red-600">
                            {trade.sell_trade.exchange} @ {trade.sell_trade.price.toFixed(trade.symbol.endsWith("USDT") ? 2 : 8)}
                          </Badge>
                        </TableCell>
                        <TableCell className={`text-right font-medium ${trade.profit_quote >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {trade.profit_quote.toFixed(2)}
                        </TableCell>
                        <TableCell className={`text-right font-medium ${trade.profit_percentage >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {trade.profit_percentage.toFixed(4)}%
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-gray-500 py-8">
                        No test trades recorded yet.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      {/* Alerts and Failsafe Status (Contextual) */}
      {(recentAlerts.length > 0 || failsafeStatus?.global_trading_halt) && (
        <Card className="mt-6 bg-gray-800/50 border-gray-700">
            <CardHeader>
                <CardTitle className="text-white flex items-center"><Info size={20} className="mr-2 text-yellow-400"/>Important Notices</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
                {failsafeStatus?.global_trading_halt && (
                    <Alert variant="destructive">
                        <AlertCircle className="h-4 w-4" />
                        <AlertTitle>Global Trading Halt Activated!</AlertTitle>
                        <AlertDescription>
                            Reason: {failsafeStatus.global_halt_reason || "Not specified"}. Trading is currently stopped.
                            {failsafeStatus.global_halt_timestamp && ` (Since: ${new Date(failsafeStatus.global_halt_timestamp).toLocaleString()})`}
                        </AlertDescription>
                    </Alert>
                )}
                {recentAlerts.map(alert => (
                    <Alert key={alert.id || alert.timestamp} variant={alert.severity === "critical" || alert.severity === "error" ? "destructive" : "default"} className={alert.severity === "warning" ? "bg-yellow-700/20 border-yellow-600 text-yellow-300" : "bg-gray-700/30 border-gray-600"}>
                        <AlertCircle className="h-4 w-4" />
                        <AlertTitle>{alert.type.replace(/_/g, " ").toUpperCase()}</AlertTitle>
                        <AlertDescription>{alert.message} <span className="text-xs text-gray-500">({formatDistanceToNow(new Date(alert.timestamp), { addSuffix: true })})</span></AlertDescription>
                    </Alert>
                ))}
            </CardContent>
        </Card>
      )}
    </div>
  );
}

