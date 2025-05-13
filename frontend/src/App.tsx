import { useState, useEffect, useCallback } from "react";
import ConnectTab from "./components/ConnectTab";
import DashboardTab from "./components/DashboardTab";
import TestModeTab from "./components/TestModeTab";
import { exchangeApi, botApi, connectWebSocket } from "./api";
import {
  ArbitrageTrade,
  BotStatusPayload, // MODIFICATION: Using the more comprehensive BotStatusPayload
  ExchangeBalance,
  TestModeSettings,
  AlertMessage,
  FailsafeStatusData,
  WebSocketMessage,
  TestSimulationStatusPayload,
} from "./types";
import "./index.css";
import { useToast } from "./hooks/use-toast";
import { Toaster } from "./components/ui/toaster";

function App() {
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState("connect"); // Default to Live tab (renamed from connect)

  // Consolidated Bot Status from backend (WebSocket)
  const [botStatus, setBotStatus] = useState<BotStatusPayload | null>(null);
  // Specific Test Simulation Status from WebSocket
  const [testSimulationStatus, setTestSimulationStatus] = useState<TestSimulationStatusPayload | null>(null);

  const [supportedExchanges, setSupportedExchanges] = useState<string[]>([]);
  const [balances, setBalances] = useState<ExchangeBalance[]>([]);
  const [liveTrades, setLiveTrades] = useState<ArbitrageTrade[]>([]);
  const [testTrades, setTestTrades] = useState<ArbitrageTrade[]>([]);
  const [alerts, setAlerts] = useState<AlertMessage[]>([]); // This will be part of botStatus from WS
  const [failsafeStatus, setFailsafeStatus] = useState<FailsafeStatusData | null>(null); // This will be part of botStatus from WS

  const [error, setError] = useState<string | null>(null); // General error state for non-toast errors
  const [wsConnected, setWsConnected] = useState(false);
  const [wsReconnecting, setWsReconnecting] = useState(false);
  // const [wsConnectionAttempted, setWsConnectionAttempted] = useState(false); // Managed by connectWebSocket now

  // Initial data fetch (non-WebSocket dependent parts)
  const fetchInitialStaticData = useCallback(async () => {
    try {
      const exchangesResponse = await exchangeApi.getSupportedExchanges();
      setSupportedExchanges(exchangesResponse.exchanges);
      // Fetch initial bot status via HTTP as WebSocket might not be connected yet
      const initialStatus = await botApi.getStatus();
      setBotStatus(initialStatus);
      setFailsafeStatus(initialStatus.failsafe_status);
      setAlerts(initialStatus.active_alerts.map(a => ({...a, id: a.id || (a.timestamp + Math.random().toString()) })));
      
      // Fetch initial balances and trades if exchanges are connected
      if (initialStatus.connected_exchanges && initialStatus.connected_exchanges.length > 0) {
        const balancesResponse = await exchangeApi.getBalances();
        setBalances(balancesResponse); // API returns List[ExchangeBalance]
        const liveTradesResponse = await botApi.getTrades(50, false);
        setLiveTrades(liveTradesResponse);
        const testTradesResponse = await botApi.getTrades(50, true);
        setTestTrades(testTradesResponse);
      }

    } catch (err: any) {
      const errorMessage = err.message || "Failed to fetch initial application data";
      setError(errorMessage);
      toast({
        variant: "destructive",
        title: "Initial Data Load Error",
        description: errorMessage,
      });
      console.error("Error fetching initial static data:", err);
    }
  }, [toast]);

  useEffect(() => {
    fetchInitialStaticData();
  }, [fetchInitialStaticData]);

  useEffect(() => {
    let wsInstance: { disconnect: () => void; reconnect: () => void } | null = null;

    const handleWebSocketMessage = (message: WebSocketMessage) => {
      // console.log("App.tsx: WebSocket message received:", message);
      const { type, payload } = message;

      switch (type) {
        case "initial_status": // Handle the full initial status dump
        case "bot_status_update":
          if (payload.bot_status) setBotStatus(payload.bot_status as BotStatusPayload);
          if (payload.test_simulation_status) setTestSimulationStatus(payload.test_simulation_status as TestSimulationStatusPayload);
          if (payload.exchange_balances) setBalances(payload.exchange_balances as ExchangeBalance[]);
          if (payload.recent_trades) { // Assuming recent_trades might be mixed or specific to current mode
            const currentMode = payload.bot_status?.current_mode || botStatus?.current_mode;
            if (currentMode === "test_simulating") {
              setTestTrades((payload.recent_trades as ArbitrageTrade[]).filter(t => t.is_test_trade).slice(0,100));
            } else if (currentMode === "live") {
              setLiveTrades((payload.recent_trades as ArbitrageTrade[]).filter(t => !t.is_test_trade).slice(0,100));
            }
          }
          if (payload.bot_status?.active_alerts) setAlerts(payload.bot_status.active_alerts.map(a => ({...a, id: a.id || (a.timestamp + Math.random().toString()) })));
          if (payload.bot_status?.failsafe_status) setFailsafeStatus(payload.bot_status.failsafe_status);
          break;
        case "new_trade":
          const trade = payload as ArbitrageTrade;
          if (trade.is_test_trade) {
            setTestTrades(prev => [trade, ...prev].slice(0, 100));
          } else {
            setLiveTrades(prev => [trade, ...prev].slice(0, 100));
          }
          toast({
            title: `${trade.is_test_trade ? "Test" : "Live"} Trade Executed`,
            description: `${trade.symbol} on ${trade.buy_trade.exchange} -> ${trade.sell_trade.exchange}. Profit: ${trade.profit_percentage.toFixed(4)}%`,
          });
          break;
        case "new_alert":
          const alert = payload as AlertMessage;
          setAlerts(prev => [{...alert, id: alert.id || (alert.timestamp + Math.random().toString())}, ...prev].slice(0, 50));
          toast({
            variant: alert.severity === "critical" || alert.severity === "error" ? "destructive" : alert.severity === "warning" ? "default" : "default",
            title: `Alert: ${alert.type.replace(/_/g, " ").toUpperCase()}`,
            description: alert.message,
          });
          break;
        case "balances_update": // This might be part of bot_status_update now
          setBalances(payload.balances as ExchangeBalance[]);
          break;
        case "test_simulation_update": // This is now part of bot_status_update
          setTestSimulationStatus(payload as TestSimulationStatusPayload);
          break;
        case "failsafe_status_update": // This is now part of bot_status_update
          setFailsafeStatus(payload as FailsafeStatusData);
          break;
        default:
          console.warn("App.tsx: Unhandled WebSocket message type:", type, payload);
      }
    };

    wsInstance = connectWebSocket(
      handleWebSocketMessage,
      (connected) => {
        setWsConnected(connected);
        setBotStatus(prev => prev ? { ...prev, websocket_connected: connected } : null);
        if (connected) {
          setWsReconnecting(false);
          // Initial status is sent by connectWebSocket onopen, no need to fetchAllBackendData here
        }
      },
      (isReconnecting) => {
        setWsReconnecting(isReconnecting);
        if (isReconnecting) {
          setBotStatus(prev => prev ? { ...prev, websocket_connected: false } : null); // Show disconnected while reconnecting
        }
      }
    );

    return () => {
      if (wsInstance) {
        wsInstance.disconnect();
      }
    };
  }, [toast]); // Removed fetchAllBackendData from dependencies as WS handles updates

  const handleBotAction = useCallback(async (action: "start_live" | "start_test" | "stop", settings?: TestModeSettings) => {
    setError(null);
    try {
      let response;
      const requestBody = { mode: action === "start_live" ? "live" : "test", test_settings: settings };
      
      if (action === "start_live" || action === "start_test") {
        response = await botApi.startBot(action === "start_test", settings);
        toast({ title: `${action === "start_live" ? "Live Bot" : "Test Simulation"} Starting`, description: response.message });
      } else if (action === "stop") {
        response = await botApi.stopBot();
        toast({ title: "Bot Stopping", description: response.message });
      } else {
        throw new Error("Invalid bot action");
      }
      // Backend state changes should now be reflected via WebSocket updates.
      // No need for manual fetchAllBackendData here.
    } catch (err: any) {
      const errorMessage = err.message || `Failed to ${action.replace("_", " ")}`;
      setError(errorMessage);
      toast({ variant: "destructive", title: "Bot Action Error", description: errorMessage });
    }
  }, [toast]);

  const handleFailsafeReactivation = useCallback(async (type: "pair" | "exchange" | "global", entity_name?: string) => {
    setError(null);
    try {
      const response = await botApi.reactivateFailsafe({type, entity_name});
      toast({ title: "Reactivation Attempted", description: response.message });
      // Status update will come via WebSocket
    } catch (err: any) {
      const errorMessage = err.message || `Failed to reactivate ${entity_name || type}`;
      setError(errorMessage);
      toast({ variant: "destructive", title: "Reactivation Error", description: errorMessage });
    }
  }, [toast]);

  const currentBotStatusForTabs = botStatus || {
    is_bot_running: false,
    current_mode: "idle",
    connected_exchanges: [],
    websocket_connected: wsConnected,
    last_status_update_ts: new Date().toISOString(),
    active_alerts: [],
    failsafe_status: { global_trading_halt: false, disabled_exchanges: {}, disabled_pairs: {} },
  } as BotStatusPayload;

  const currentTestSimStatusForTabs = testSimulationStatus || {
    status: "IDLE",
    total_test_trades: 0,
    total_test_profit: 0
  } as TestSimulationStatusPayload;

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 to-gray-800 text-white font-sans">
      <header className="border-b border-gray-700 bg-gray-800 py-4 sticky top-0 z-20">
        <div className="container mx-auto px-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-orange-500 to-red-600 bg-clip-text text-transparent">
              Crypto Arbitrage Bot
            </h1>
            <div className="flex items-center space-x-2">
              <div className={
                wsConnected
                  ? "h-3 w-3 rounded-full bg-green-500 shadow-md shadow-green-500/50"
                  : wsReconnecting
                    ? "h-3 w-3 rounded-full bg-yellow-500 animate-pulse shadow-md shadow-yellow-500/50"
                    : "h-3 w-3 rounded-full bg-red-500 shadow-md shadow-red-500/50"
              }></div>
              <span className="text-sm text-gray-400">
                {wsConnected ? "Connected" : wsReconnecting ? "Reconnecting" : "Disconnected"}
              </span>
            </div>
          </div>
        </div>
      </header>
      
      <main className="container mx-auto px-4 py-6 pb-20 md:pb-6">
        <Toaster />
        
        {error && (
          <div className="mb-4 p-4 bg-red-700/20 border border-red-500 text-red-300 rounded-md">
            <p><strong>Error:</strong> {error}</p>
            <button onClick={() => setError(null)} className="text-xs underline mt-1">Dismiss</button>
          </div>
        )}

        <div className="w-full">
          {/* Desktop Tabs */}
          <div className="border-b border-gray-700 mb-6 md:block hidden">
            <div className="flex space-x-1">
              {[
                { key: "connect", label: "Live" },
                { key: "dashboard", label: "Stats" },
                { key: "test", label: "Test" },
              ].map(tab => (
                <button 
                  key={tab.key}
                  className={`py-3 px-5 rounded-t-md text-sm font-medium transition-colors duration-150 ${activeTab === tab.key ? "bg-gray-700/50 border-b-2 border-orange-500 text-white" : "text-gray-400 hover:text-white hover:bg-gray-700/30"}`}
                  onClick={() => setActiveTab(tab.key)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
          
          {activeTab === "connect" && (
            <ConnectTab 
              botStatus={currentBotStatusForTabs} 
              onBotAction={handleBotAction}
              supportedExchanges={supportedExchanges}
              balances={balances}
              alerts={alerts} // Pass down alerts from botStatus or separate state
              failsafeStatus={failsafeStatus} // Pass down failsafeStatus from botStatus or separate state
              onReactivateFailsafe={handleFailsafeReactivation}
            />
          )}
          
          {activeTab === "dashboard" && (
            <DashboardTab 
              liveTrades={liveTrades} 
              testTrades={testTrades}
              balances={balances}
              isTestMode={currentBotStatusForTabs.current_mode === "test_simulating"}
              isRunning={currentBotStatusForTabs.is_bot_running}
              alerts={alerts}
              failsafeStatus={failsafeStatus}
              onReactivateFailsafe={handleFailsafeReactivation}
            />
          )}
          
          {activeTab === "test" && (
            <TestModeTab 
              testSimulationStatus={currentTestSimStatusForTabs}
              supportedExchanges={supportedExchanges}
              testTrades={testTrades}
              onBotAction={handleBotAction}
              alerts={alerts.filter(a => a.message.toLowerCase().includes("test") || a.severity === "critical" || a.severity === "error")} // Filter alerts for test tab
              failsafeStatus={failsafeStatus} // Failsafes might still be relevant to show
              // onReactivateFailsafe={handleFailsafeReactivation} // Reactivation might not be typical from test tab
            />
          )}
        </div>

        {/* Mobile Tabs - Bottom Navigation */}
        <div className="md:hidden fixed bottom-0 left-0 right-0 bg-gray-800 border-t border-gray-700 shadow-lg z-20">
          <div className="flex justify-around">
            {[
              { key: "connect", label: "Live" },
              { key: "dashboard", label: "Stats" },
              { key: "test", label: "Test" },
            ].map(tab => (
              <button 
                key={tab.key}
                className={`flex-1 py-3 text-xs font-medium transition-colors duration-150 ${activeTab === tab.key ? "bg-orange-500 text-white" : "text-gray-400 hover:text-white hover:bg-gray-700"}`}
                onClick={() => setActiveTab(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;

