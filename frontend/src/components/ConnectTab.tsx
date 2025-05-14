import { useState, useEffect } from "react";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
import { exchangeApi, botApi } from "../api";
import { BotStatusPayload, ExchangeBalance, AlertMessage, FailsafeStatusData } from "../types"; // Ensure BotStatusPayload is the correct type used by App.tsx
import { AlertCircle, CheckCircle, Play, Square } from "lucide-react";

interface ConnectTabProps {
  botStatus: BotStatusPayload; // Changed from BotStatus to BotStatusPayload for clarity and consistency
  onBotAction: (action: "start_live" | "stop") => Promise<void>;
  supportedExchanges: string[];
  balances: ExchangeBalance[]; 
  alerts: AlertMessage[]; // Assuming alerts are passed down if needed
  failsafeStatus: FailsafeStatusData | null; // Assuming failsafeStatus is passed down
  onReactivateFailsafe: (type: "pair" | "exchange" | "global", entity?: string) => Promise<void>; // Added from App.tsx
}

export default function ConnectTab({
  botStatus,
  onBotAction,
  supportedExchanges,
  // balances, // Balances are now fetched within the component if needed, or rely on botStatus for connected exchanges' balances
  // alerts, // Alerts are handled globally or in specific tabs like Dashboard
  // failsafeStatus,
  // onReactivateFailsafe
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
        setConnectSuccess(`Successfully connected to ${selectedExchange}. Status will update via WebSocket.`);
        // App.tsx's WebSocket listener will update botStatus, including connected_exchanges
        // No need to call botApi.getStatus() here if WebSocket updates are reliable.
        setApiKey("");
        setApiSecret("");
        setAdditionalParams("");
      } else {
        setConnectError(connectResult.message || "Failed to connect to exchange.");
      }
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || error.message || "Failed to connect to exchange";
      setConnectError(errorMessage);
      console.error("ConnectTab connect error:", error.response?.data || error);
    }
  };

  const handleStartStop = async () => {
    try {
      setActionError(null);
      if (botStatus.is_running) {
        await onBotAction("stop");
      } else {
        if (!botStatus.connected_exchanges || botStatus.connected_exchanges.length < 2) { // FIX: Use connected_exchanges
          setActionError("Minimum 2 exchanges must be connected to start the bot.");
          return;
        }
        await onBotAction("start_live");
      }
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || error.message || "Failed to start/stop bot";
      setActionError(errorMessage);
      console.error("ConnectTab start/stop error:", error.response?.data || error);
    }
  };
  
  // Helper to get balance for a specific exchange and asset from botStatus.exchange_balances
  const getExchangeBalanceDisplay = (exchangeId: string, asset: string): string => {
    const exchangeBal = botStatus.exchange_balances?.find(b => b.exchange === exchangeId);
    return exchangeBal?.balances[asset]?.free?.toFixed(2) ?? "N/A";
  };

  return (
    <div className="space-y-6">
      {connectError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Connection Error</AlertTitle>
          <AlertDescription>{typeof connectError === 'object' ? JSON.stringify(connectError) : connectError}</AlertDescription>
        </Alert>
      )}
      {connectSuccess && (
        <Alert variant="success" className="mb-4">
          <CheckCircle className="h-4 w-4" />
          <AlertTitle>Connection Success</AlertTitle>
          <AlertDescription>{connectSuccess}</AlertDescription>
        </Alert>
      )}
      {actionError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Action Error</AlertTitle>
          <AlertDescription>{typeof actionError === 'object' ? JSON.stringify(actionError) : actionError}</AlertDescription>
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
                placeholder='{"param1": "value1"}'
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
                <div className={`p-4 rounded-md mb-4 ${botStatus.is_running && botStatus.current_mode === 'live' ? "bg-green-700/30 border-green-500" : "bg-red-700/30 border-red-500"} border`}>
                    <div className="flex items-center">
                        {botStatus.is_running && botStatus.current_mode === 'live' ? <CheckCircle className="h-5 w-5 text-green-400 mr-2" /> : <AlertCircle className="h-5 w-5 text-red-400 mr-2" />}
                        <span className={`text-lg font-medium ${botStatus.is_running && botStatus.current_mode === 'live' ? "text-green-300" : "text-red-300"}`}>
                            Bot Status: {botStatus.is_running && botStatus.current_mode === 'live' ? "Running (Live Mode)" : "Stopped"}
                        </span>
                    </div>
                </div>
              {(!botStatus.connected_exchanges || botStatus.connected_exchanges.length < 2) && !(botStatus.is_running && botStatus.current_mode === 'live') && (
                <Alert variant="warning" className="mb-4">
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
                className={`w-full text-white font-semibold py-3 px-4 rounded-md transition-colors duration-150 flex items-center justify-center space-x-2 ${botStatus.is_running && botStatus.current_mode === 'live' ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}`}
                disabled={(!botStatus.connected_exchanges || botStatus.connected_exchanges.length < 2) && !(botStatus.is_running && botStatus.current_mode === 'live')}
              >
                {botStatus.is_running && botStatus.current_mode === 'live' ? <Square size={20}/> : <Play size={20}/>}
                <span>{botStatus.is_running && botStatus.current_mode === 'live' ? "Stop Live Bot" : "Start Live Bot"}</span>
              </Button>
            </CardFooter>
          </Card>

          <Card className="bg-gray-800/50 border-gray-700">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white">Connected Exchanges</CardTitle>
            </CardHeader>
            <CardContent>
              {botStatus.connected_exchanges && botStatus.connected_exchanges.length > 0 ? ( // FIX: Use connected_exchanges
                <ul className="space-y-2">
                  {botStatus.connected_exchanges.map((exchange) => { // FIX: Use connected_exchanges
                    const balance = botStatus.exchange_balances?.find(b => b.exchange === exchange);
                    const usdtAmount = balance?.balances?.USDT?.free?.toFixed(2) ?? "N/A";
                    const status = balance ? (balance.error ? "Error" : "OK") : "Fetching...";
                    return (
                        <li key={exchange} className="flex justify-between items-center p-3 bg-gray-700/70 border border-gray-600 rounded-md">
                          <span className="font-medium text-gray-200">
                            {exchange.charAt(0).toUpperCase() + exchange.slice(1)}
                          </span>
                          <div className="text-right">
                            <div className={`flex items-center ${status === "OK" ? "text-green-400" : status === "Error" ? "text-red-400" : "text-yellow-400"}`}>
                                {status === "OK" && <CheckCircle className="h-4 w-4 mr-1" />}
                                {status === "Error" && <AlertCircle className="h-4 w-4 mr-1" />}
                                <span className="text-sm">{status}</span>
                            </div>
                            <span className="text-xs text-gray-400">
                                USDT: {usdtAmount}
                            </span>
                          </div>
                        </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-center text-gray-400 py-4">No exchanges connected.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

