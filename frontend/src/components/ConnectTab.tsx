import { useState, useEffect } from "react";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert"; // MODIFICATION: Added AlertTitle
import { exchangeApi, botApi } from "../api";
import { BotStatus, ExchangeBalance, AlertMessage, FailsafeStatusData } from "../types"; // MODIFICATION: Added AlertMessage, FailsafeStatusData
import { AlertCircle, CheckCircle, RefreshCw, Play, StopCircle, PowerOff, Power } from "lucide-react"; // MODIFICATION: Added PowerOff, Power

interface ConnectTabProps {
  botStatus: BotStatus;
  // onBotStatusChange: (running: boolean) => void; // MODIFICATION: Replaced with onBotAction
  onBotAction: (action: "start_live" | "stop") => Promise<void>; // MODIFICATION: Unified bot action
  supportedExchanges: string[]; // MODIFICATION: Pass supported exchanges as prop
  balances: ExchangeBalance[]; // MODIFICATION: Pass balances as prop
  alerts: AlertMessage[];
  failsafeStatus: FailsafeStatusData | null;
  onReactivate: (type: "pair" | "exchange" | "global", entity?: string) => Promise<void>;
}

export default function ConnectTab({
  botStatus,
  onBotAction,
  supportedExchanges,
  balances,
  alerts,
  failsafeStatus,
  onReactivate
}: ConnectTabProps) {
  const [selectedExchange, setSelectedExchange] = useState<string>("");
  const [apiKey, setApiKey] = useState<string>("");
  const [apiSecret, setApiSecret] = useState<string>("");
  const [additionalParams, setAdditionalParams] = useState<string>("");
  const [connectError, setConnectError] = useState<string | null>(null);
  const [connectSuccess, setConnectSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (supportedExchanges.length > 0 && !selectedExchange) {
      setSelectedExchange(supportedExchanges[0]);
    }
  }, [supportedExchanges, selectedExchange]);

  const handleConnect = async () => {
    try {
      setConnectError(null);
      setConnectSuccess(null);
      setActionError(null);

      if (!selectedExchange) {
        setConnectError("Please select an exchange");
        return;
      }
      if (!apiKey || !apiSecret) {
        setConnectError("API key and secret are required");
        return;
      }

      let parsedParams = {};
      if (additionalParams) {
        try {
          parsedParams = JSON.parse(additionalParams);
        } catch (e) {
          setConnectError("Invalid additional parameters format. Use valid JSON.");
          return;
        }
      }

      const connectResult = await exchangeApi.connectExchange({
        exchange: selectedExchange,
        api_key: apiKey,
        api_secret: apiSecret,
        additional_params: parsedParams,
      });

      if (connectResult.success) {
        setConnectSuccess(`Successfully connected to ${selectedExchange}. Balances will update shortly.`);
        // Trigger a refresh of bot status which should include connected exchanges
        // This will be handled by App.tsx polling or WebSocket update
        await botApi.getStatus(); // Force a status refresh to update connected exchanges list in App.tsx
        setApiKey("");
        setApiSecret("");
        setAdditionalParams("");
      } else {
        setConnectError(connectResult.message || "Failed to connect to exchange.");
      }
    } catch (error: any) {
      setConnectError(error.message || "Failed to connect to exchange");
    }
  };

  const handleStartStop = async () => {
    try {
      setActionError(null);
      if (botStatus.is_running) {
        await onBotAction("stop");
      } else {
        if (!botStatus.active_exchanges || botStatus.active_exchanges.length < 2) {
          setActionError("Minimum 2 exchanges must be connected to start the bot.");
          return;
        }
        await onBotAction("start_live");
      }
    } catch (error: any) {
      setActionError(error.message || "Failed to start/stop bot");
    }
  };

  const getExchangeBalance = (exchangeId: string, asset: string): number => {
    const exchangeBal = balances.find(b => b.exchange === exchangeId);
    return exchangeBal?.balances[asset]?.free ?? 0;
  };

  return (
    <div className="space-y-6">
      {/* Page Title - Consistent with other tabs */}
      {/* <h2 className="text-3xl font-bold tracking-tight text-white">Live Mode</h2> */}
      {/* <p className="text-gray-400">Connect to exchanges and manage the live arbitrage bot.</p> */}

      {connectError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Connection Error</AlertTitle>
          <AlertDescription>{connectError}</AlertDescription>
        </Alert>
      )}
      {connectSuccess && (
        <Alert variant="success" className="mb-4"> {/* MODIFICATION: Shadcn doesn't have success, use custom or default */}
          <CheckCircle className="h-4 w-4" />
          <AlertTitle>Connection Success</AlertTitle>
          <AlertDescription>{connectSuccess}</AlertDescription>
        </Alert>
      )}
      {actionError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Action Error</AlertTitle>
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white">Connect Exchange</CardTitle>
            <CardDescription className="text-gray-400">
              Add your exchange API credentials to connect.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label htmlFor="exchange" className="text-gray-300">Exchange</Label>
              <select 
                id="exchange"
                className="w-full p-2 mt-1 border border-gray-600 rounded-md bg-gray-700 text-white focus:ring-orange-500 focus:border-orange-500"
                value={selectedExchange}
                onChange={(e) => setSelectedExchange(e.target.value)}
              >
                {supportedExchanges.map((exchange) => (
                  <option key={exchange} value={exchange}>
                    {exchange.charAt(0).toUpperCase() + exchange.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="apiKey" className="text-gray-300">API Key</Label>
              <Input
                id="apiKey"
                type="text"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Enter your API key"
                className="bg-gray-700 border-gray-600 text-white placeholder-gray-500 focus:ring-orange-500 focus:border-orange-500 mt-1"
              />
            </div>
            <div>
              <Label htmlFor="apiSecret" className="text-gray-300">API Secret</Label>
              <Input
                id="apiSecret"
                type="password"
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                placeholder="Enter your API secret"
                className="bg-gray-700 border-gray-600 text-white placeholder-gray-500 focus:ring-orange-500 focus:border-orange-500 mt-1"
              />
            </div>
            <div>
              <Label htmlFor="additionalParams" className="text-gray-300">Additional Parameters (JSON, optional)</Label>
              <Input
                id="additionalParams"
                type="text"
                value={additionalParams}
                onChange={(e) => setAdditionalParams(e.target.value)}
                placeholder=\'{"param1": "value1"}\'
                className="bg-gray-700 border-gray-600 text-white placeholder-gray-500 focus:ring-orange-500 focus:border-orange-500 mt-1"
              />
            </div>
          </CardContent>
          <CardFooter>
            <Button onClick={handleConnect} className="w-full bg-blue-600 hover:bg-blue-700 text-white">
              Connect Exchange
            </Button>
          </CardFooter>
        </Card>

        <div className="space-y-6">
          <Card className="bg-gray-800/50 border-gray-700">
            <CardHeader>
              <CardTitle className="text-white">Bot Control</CardTitle>
              <CardDescription className="text-gray-400">
                Start or stop the live arbitrage bot.
              </CardDescription>
            </CardHeader>
            <CardContent>
                <div className={`p-4 rounded-md mb-4 ${botStatus.is_running ? "bg-green-700/30 border-green-500" : "bg-red-700/30 border-red-500"} border`}>
                    <div className="flex items-center">
                        {botStatus.is_running ? <CheckCircle className="h-5 w-5 text-green-400 mr-2" /> : <AlertCircle className="h-5 w-5 text-red-400 mr-2" />}
                        <span className={`text-lg font-medium ${botStatus.is_running ? "text-green-300" : "text-red-300"}`}>
                            Bot Status: {botStatus.is_running ? "Running (Live Mode)" : "Stopped"}
                        </span>
                    </div>
                </div>
              {(!botStatus.active_exchanges || botStatus.active_exchanges.length < 2) && !botStatus.is_running && (
                <Alert variant="warning" className="mb-4"> {/* MODIFICATION: Shadcn doesn't have warning, use custom or default */}
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Minimum Exchanges Required</AlertTitle>
                  <AlertDescription>
                    Please connect at least two exchanges to start the bot.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
            <CardFooter>
              <Button 
                onClick={handleStartStop}
                className={`w-full text-white font-semibold py-3 px-4 rounded-md transition-colors duration-150 flex items-center justify-center space-x-2 ${botStatus.is_running ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}`}
                disabled={(!botStatus.active_exchanges || botStatus.active_exchanges.length < 2) && !botStatus.is_running}
              >
                {botStatus.is_running ? <StopCircle size={20}/> : <Play size={20}/>}
                <span>{botStatus.is_running ? "Stop Live Bot" : "Start Live Bot"}</span>
              </Button>
            </CardFooter>
          </Card>

          <Card className="bg-gray-800/50 border-gray-700">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white">Connected Exchanges</CardTitle>
              {/* <Button variant="outline" size="icon" onClick={async () => await botApi.getStatus()} title="Refresh connection status" className="text-gray-400 hover:text-white border-gray-600 hover:bg-gray-700">
                <RefreshCw className="h-4 w-4" /> 
              </Button> */} 
              {/* Refresh is handled by App.tsx polling/WS */}
            </CardHeader>
            <CardContent>
              {botStatus.active_exchanges && botStatus.active_exchanges.length > 0 ? (
                <ul className="space-y-2">
                  {botStatus.active_exchanges.map((exchange) => (
                    <li key={exchange} className="flex justify-between items-center p-3 bg-gray-700/70 border border-gray-600 rounded-md">
                      <span className="font-medium text-gray-200">
                        {exchange.charAt(0).toUpperCase() + exchange.slice(1)}
                      </span>
                      <div className="text-right">
                        <div className="flex items-center text-green-400">
                            <CheckCircle className="h-4 w-4 mr-1" />
                            <span className="text-sm">Connected</span>
                        </div>
                        <span className="text-xs text-gray-400">
                            USDT: {getExchangeBalance(exchange, "USDT").toFixed(2)}
                        </span>
                        {/* Add other key asset balances if needed */}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-center text-gray-400 py-4">No exchanges connected.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Alerts and Failsafes Section - Moved from Dashboard to be more general if needed, or keep in Dashboard */}
      {/* For now, assuming Alerts and Failsafes are primarily on DashboardTab */}
    </div>
  );
}

