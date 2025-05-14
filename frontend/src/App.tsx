import { useState, useEffect, useCallback } from "react";
import ConnectTab from "./components/ConnectTab";
import DashboardTab from "./components/DashboardTab";
import TestModeTab from "./components/TestModeTab";
import { exchangeApi, botApi, connectWebSocket } from "./api";
import {
  ArbitrageTrade,
  BotStatusPayload,
  ExchangeBalance,
  TestModeSettings,
  AlertMessage,
  FailsafeStatusData,
  WebSocketMessage,
  TestSimulationStatusPayload,
} from "./types";
import "./index.css"; // Ensure this contains necessary base styles and Tailwind directives
import { useToast } from "./hooks/use-toast";
import { Toaster } from "./components/ui/toaster";

function App() {
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState("connect"); 

  const [botStatus, setBotStatus] = useState<BotStatusPayload | null>(null);
  const [testSimulationStatus, setTestSimulationStatus] = useState<TestSimulationStatusPayload | null>(null);

  const [supportedExchanges, setSupportedExchanges] = useState<string[]>([]);
  const [balances, setBalances] = useState<ExchangeBalance[]>([]);
  const [liveTrades, setLiveTrades] = useState<ArbitrageTrade[]>([]);
  const [testTrades, setTestTrades] = useState<ArbitrageTrade[]>([]);
  const [alerts, setAlerts] = useState<AlertMessage[]>([]);
  const [failsafeStatus, setFailsafeStatus] = useState<FailsafeStatusData | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [wsReconnecting, setWsReconnecting] = useState(false);

  const fetchInitialStaticData = useCallback(async () => {
    try {
      const exchangesResponse = await exchangeApi.getSupportedExchanges();
      setSupportedExchanges(exchangesResponse.exchanges);
      const initialStatus = await botApi.getStatus();
      setBotStatus(initialStatus);
      setFailsafeStatus(initialStatus.failsafe_status);
      setAlerts(initialStatus.active_alerts.map(a => ({...a, id: a.id || (a.timestamp + Math.random().toString()) })));
      
      if (initialStatus.connected_exchanges && initialStatus.connected_exchanges.length > 0) {
        const balancesResponse = await exchangeApi.getBalances();
        setBalances(balancesResponse);
        const liveTradesResponse = await botApi.getTrades(50, false);
        setLiveTrades(liveTradesResponse);
        const testTradesResponse = await botApi.getTrades(50, true);
        setTestTrades(testTradesResponse);
      }
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || "Failed to fetch initial application data";
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
      const { type, payload } = message;
      switch (type) {
        case "initial_status":
        case "bot_status_update":
          if (payload.bot_status) setBotStatus(payload.bot_status as BotStatusPayload);
          if (payload.test_simulation_status) setTestSimulationStatus(payload.test_simulation_status as TestSimulationStatusPayload);
          if (payload.exchange_balances) setBalances(payload.exchange_balances as ExchangeBalance[]);
          if (payload.recent_trades) {
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
          const alertMsg = payload as AlertMessage;
          setAlerts(prev => [{...alertMsg, id: alertMsg.id || (alertMsg.timestamp + Math.random().toString())}, ...prev].slice(0, 50));
          toast({
            variant: alertMsg.severity === "critical" || alertMsg.severity === "error" ? "destructive" : alertMsg.severity === "warning" ? "default" : "default",
            title: `Alert: ${alertMsg.type.replace(/_/g, " ").toUpperCase()}`,
            description: alertMsg.message,
          });
          break;
        default:
          console.warn("App.tsx: Unhandled WebSocket message type:", type, payload);
      }
    };

    wsInstance = connectWebSocket(
      handleWebSocketMessage,
      (connected) => {
        setWsConnected(connected);
        setBotStatus(prev => prev ? { ...prev, websocket_connected: connected } : { ...currentBotStatusForTabs, websocket_connected: connected });
        if (connected) {
          setWsReconnecting(false);
        }
      },
      (isReconnecting) => {
        setWsReconnecting(isReconnecting);
        if (isReconnecting) {
          setBotStatus(prev => prev ? { ...prev, websocket_connected: false } : { ...currentBotStatusForTabs, websocket_connected: false });
        }
      }
    );

    return () => {
      if (wsInstance) {
        wsInstance.disconnect();
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast]);

  const handleBotAction = useCallback(async (action: "start_live" | "start_test" | "stop", settings?: TestModeSettings) => {
    setError(null);
    try {
      let response;
      if (action === "start_live" || action === "start_test") {
        response = await botApi.startBot(action === "start_test", settings);
        toast({ title: `${action === "start_live" ? "Live Bot" : "Test Simulation"} Starting`, description: response.message });
      } else if (action === "stop") {
        response = await botApi.stopBot();
        toast({ title: "Bot Stopping", description: response.message });
      } else {
        throw new Error("Invalid bot action");
      }
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || `Failed to ${action.replace("_", " ")}`;
      setError(errorMessage);
      toast({ variant: "destructive", title: "Bot Action Error", description: errorMessage });
      console.error("Bot Action Error:", err.response?.data || err);
    }
  }, [toast]);

  const handleFailsafeReactivation = useCallback(async (type: "pair" | "exchange" | "global", entity_name?: string) => {
    setError(null);
    try {
      const response = await botApi.reactivateFailsafe({type, entity_name});
      toast({ title: "Reactivation Attempted", description: response.message });
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || `Failed to reactivate ${entity_name || type}`;
      setError(errorMessage);
      toast({ variant: "destructive", title: "Reactivation Error", description: errorMessage });
    }
  }, [toast]);

  const currentBotStatusForTabs = botStatus || {
    is_bot_running: false,
    current_mode: "idle",
    connected_exchanges: [],
    exchange_balances: [], // Ensure this is part of the default structure if ConnectTab relies on it
    websocket_connected: wsConnected,
    last_status_update_ts: new Date().toISOString(),
    active_alerts: [],
    failsafe_status: { global_trading_halt: false, disabled_exchanges: {}, disabled_pairs: {} },
  } as BotStatusPayload;

  const currentTestSimStatusForTabs = testSimulationStatus || {
    status: "IDLE",
    message: "Test simulation is not active.",
    total_test_trades: 0,
    total_test_profit: 0,
    error_message: null,
  } as TestSimulationStatusPayload;

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 to-gray-800 text-white font-sans flex flex-col">
      <header className="border-b border-gray-700 bg-gray-800 py-4 sticky top-0 z-30">
        <div className="container mx-auto px-4">
          <div className="flex items-center justify-between">
            <h1 className="text-xl sm:text-2xl font-bold bg-gradient-to-r from-orange-500 to-red-600 bg-clip-text text-transparent">
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
              <span className="text-xs sm:text-sm text-gray-400">
                {wsConnected ? "Connected" : wsReconnecting ? "Reconnecting" : "Disconnected"}
              </span>
            </div>
          </div>
        </div>
      </header>
      
      {/* Content area that grows to fill space, pushing mobile nav to bottom */}
      <main className="container mx-auto px-4 py-6 flex-grow pb-20 md:pb-6"> {/* Increased bottom padding for mobile nav, ensure it doesn't overlap content */}
        <Toaster />
        
        {error && (
          <div className="mb-4 p-3 sm:p-4 bg-red-700/20 border border-red-500 text-red-300 rounded-md text-xs sm:text-sm">
            <p><strong>Error:</strong> {typeof error === 'object' ? JSON.stringify(error) : error}</p>
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
              // balances prop removed as ConnectTab will use botStatus.exchange_balances
              alerts={alerts.filter(a => a.severity === "critical" || a.severity === "error" || a.message.toLowerCase().includes("connect"))} // More targeted alerts
              failsafeStatus={failsafeStatus}
              onReactivateFailsafe={handleFailsafeReactivation}
            />
          )}
          
          {activeTab === "dashboard" && (
            <DashboardTab 
              liveTrades={liveTrades} 
              testTrades={testTrades}
              balances={balances} // DashboardTab might still need the separate balances prop for its specific display
              isTestMode={currentBotStatusForTabs.current_mode === "test_simulating" || currentBotStatusForTabs.current_mode === "test_idle"}
              isRunning={currentBotStatusForTabs.is_bot_running}
              alerts={alerts}
              failsafeStatus={failsafeStatus}
              onReactivateFailsafe={handleFailsafeReactivation}
              botMode={currentBotStatusForTabs.current_mode}
            />
          )}
          
          {activeTab === "test" && (
            <TestModeTab 
              testSimulationStatus={currentTestSimStatusForTabs}
              supportedExchanges={supportedExchanges}
              testTrades={testTrades}
              onBotAction={handleBotAction}
              alerts={alerts.filter(a => a.message.toLowerCase().includes("test") || a.severity === "critical" || a.severity === "error")}
              failsafeStatus={failsafeStatus} // Pass failsafeStatus if TestModeTab needs it
            />
          )}
        </div>
      </main>

      {/* Mobile Tabs - Bottom Navigation - Increased size and padding */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 bg-gray-800 border-t border-gray-700 shadow-lg z-20">
        <div className="flex justify-around">
          {[
            { key: "connect", label: "Live" },
            { key: "dashboard", label: "Stats" },
            { key: "test", label: "Test" },
          ].map(tab => (
            <button 
              key={tab.key}
              className={`flex-1 py-3 sm:py-4 px-2 text-base font-medium transition-colors duration-150 ${activeTab === tab.key ? "bg-orange-500 text-white" : "text-gray-300 hover:text-white hover:bg-gray-700"}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default App;

