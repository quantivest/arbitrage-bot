import { useState, useEffect } from 'react';
import ConnectTab from './components/ConnectTab';
import DashboardTab from './components/DashboardTab';
import TestModeTab from './components/TestModeTab';
import { exchangeApi, botApi, connectWebSocket } from './api';
import { ArbitrageTrade, BotStatus, ExchangeBalance, TestModeSettings } from './types';
import "./index.css";
import { AlertCircle } from 'lucide-react';
import { Alert, AlertDescription } from './components/ui/alert';

function App() {
  const [activeTab, setActiveTab] = useState('connect');
  const [botStatus, setBotStatus] = useState<BotStatus>({
    running: false,
    test_mode: false,
    connected_exchanges: [],
    last_update: new Date().toISOString(),
    alerts: [],
    trades_blocked: 0,
    failsafes_triggered: 0
  });
  const [supportedExchanges, setSupportedExchanges] = useState<string[]>([]);
  const [balances, setBalances] = useState<ExchangeBalance[]>([]);
  const [trades, setTrades] = useState<ArbitrageTrade[]>([]);
  const [testTrades, setTestTrades] = useState<ArbitrageTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [wsReconnecting, setWsReconnecting] = useState(false);

  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        const exchangesResponse = await exchangeApi.getSupportedExchanges();
        setSupportedExchanges(exchangesResponse.exchanges);
        
        const statusResponse = await botApi.getStatus();
        setBotStatus(statusResponse);
        
        if (statusResponse.connected_exchanges.length > 0) {
          const balancesResponse = await exchangeApi.getBalances();
          setBalances(balancesResponse.balances);
        }
        
        if (statusResponse.running) {
          const tradesResponse = await botApi.getTrades();
          setTrades(tradesResponse.trades);
          
          if (statusResponse.test_mode) {
            const testTradesResponse = await botApi.getTrades(50, true);
            setTestTrades(testTradesResponse.trades);
          }
        }
      } catch (error: any) {
        setError(error.message || 'Failed to fetch initial data');
      }
    };
    
    fetchInitialData();
  }, []);
  
  useEffect(() => {
    let wsConnection: { socket: WebSocket | null; disconnect: () => void; reconnect: () => void } | null = null;
    
    const connectSocket = () => {
      setWsConnected(false);
      
      wsConnection = connectWebSocket(
        (data) => {
          if (data.bot_status) {
            console.log('Received bot status update:', data.bot_status);
            
            if (data.bot_status.connected_exchanges) {
              console.log('Connected exchanges in update:', data.bot_status.connected_exchanges);
            }
            
            setBotStatus(data.bot_status);
          }
          
          if (data.recent_trades) {
            const liveTrades = data.recent_trades.filter((trade: ArbitrageTrade) => !trade.is_test);
            const simulatedTrades = data.recent_trades.filter((trade: ArbitrageTrade) => trade.is_test);
            
            if (liveTrades.length > 0) {
              setTrades((prevTrades: ArbitrageTrade[]) => {
                const existingIds = new Set(prevTrades.map((t: ArbitrageTrade) => t.id));
                const newTrades = liveTrades.filter((t: ArbitrageTrade) => !existingIds.has(t.id));
                return [...newTrades, ...prevTrades].slice(0, 100); // Keep last 100 trades
              });
            }
            
            if (simulatedTrades.length > 0) {
              setTestTrades((prevTrades: ArbitrageTrade[]) => {
                const existingIds = new Set(prevTrades.map((t: ArbitrageTrade) => t.id));
                const newTrades = simulatedTrades.filter((t: ArbitrageTrade) => !existingIds.has(t.id));
                return [...newTrades, ...prevTrades].slice(0, 100); // Keep last 100 trades
              });
            }
          }
        },
        (connected) => {
          console.log('WebSocket connection status changed:', connected);
          setWsConnected(connected);
          
          if (connected) {
            botApi.getStatus()
              .then(status => {
                console.log('Initial status after WebSocket connection:', status);
                setBotStatus(status);
              })
              .catch(error => {
                console.error('Failed to fetch initial status:', error);
              });
          }
        },
        (isReconnecting) => {
          console.log('WebSocket reconnection status changed:', isReconnecting);
          setWsReconnecting(isReconnecting);
        }
      );
    };
    
    connectSocket();
    
    const statusInterval = setInterval(async () => {
      try {
        if (!wsConnected) {
          const statusResponse = await botApi.getStatus();
          console.log('Polling status update:', statusResponse);
          setBotStatus(statusResponse);
        }
      } catch (error) {
        console.error('Failed to poll status:', error);
      }
    }, 5000); // Poll every 5 seconds when WebSocket is down
    
    return () => {
      if (wsConnection) {
        wsConnection.disconnect();
      }
      clearInterval(statusInterval);
    };
  }, []);
  
  useEffect(() => {
    if (botStatus.connected_exchanges.length > 0) {
      const fetchBalances = async () => {
        try {
          const response = await exchangeApi.getBalances(true);
          setBalances(response.balances);
        } catch (error) {
          console.error('Failed to fetch balances:', error);
        }
      };
      
      fetchBalances();
      const interval = setInterval(fetchBalances, 30000);
      
      return () => clearInterval(interval);
    }
  }, [botStatus.connected_exchanges]);
  
  const handleBotStatusChange = async (running: boolean) => {
    try {
      const statusResponse = await botApi.getStatus();
      console.log('Manual status refresh:', statusResponse);
      
      setBotStatus((prev: BotStatus) => ({ 
        ...statusResponse, 
        running: running !== undefined ? running : prev.running 
      }));
    } catch (error) {
      console.error('Failed to refresh bot status:', error);
      setBotStatus((prev: BotStatus) => ({ ...prev, running }));
    }
  };
  
  const handleStartTest = async (settings: TestModeSettings) => {
    try {
      await botApi.startBot(true, settings);
      setBotStatus((prev: BotStatus) => ({ ...prev, running: true, test_mode: true }));
    } catch (error: any) {
      setError(error.message || 'Failed to start test mode');
    }
  };
  
  const handleStopTest = async () => {
    try {
      await botApi.stopBot();
      setBotStatus((prev: BotStatus) => ({ ...prev, running: false, test_mode: false }));
    } catch (error: any) {
      setError(error.message || 'Failed to stop test mode');
    }
  };
  
  const handleReactivatePair = async (pair: string) => {
    try {
      await botApi.reactivatePair(pair);
    } catch (error: any) {
      setError(error.message || `Failed to reactivate pair ${pair}`);
    }
  };
  
  const handleReactivateExchange = async (exchange: string) => {
    try {
      await botApi.reactivateExchange(exchange);
    } catch (error: any) {
      setError(error.message || `Failed to reactivate exchange ${exchange}`);
    }
  };
  
  const handleReactivateGlobal = async () => {
    try {
      await botApi.reactivateGlobal();
    } catch (error: any) {
      setError(error.message || 'Failed to reactivate global trading');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 to-gray-800 text-white">
      <header className="border-b border-gray-700 bg-gray-800 py-4">
        <div className="container mx-auto px-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-orange-500 to-red-600 bg-clip-text text-transparent">
              Crypto Arbitrage Bot
            </h1>
            <div className="flex items-center space-x-2">
              <div className={
                wsConnected 
                  ? "h-3 w-3 rounded-full bg-green-500" 
                  : wsReconnecting 
                    ? "h-3 w-3 rounded-full bg-yellow-500 animate-pulse" 
                    : "h-3 w-3 rounded-full bg-red-500"
              }></div>
              <span className="text-sm text-gray-400">
                {wsConnected 
                  ? 'Connected' 
                  : wsReconnecting 
                    ? 'Reconnecting...' 
                    : 'Disconnected'
                }
              </span>
            </div>
          </div>
        </div>
      </header>
      
      <main className="container mx-auto px-4 py-6 pb-20 md:pb-6">
        {error && (
          <Alert variant="destructive" className="mb-6">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        
        <div className="w-full">
          <div className="border-b border-gray-700 mb-6 md:block hidden">
            <div className="flex space-x-4">
              <button 
                className={activeTab === 'connect' ? "py-2 px-4 border-b-2 border-orange-500 text-white" : "py-2 px-4 text-gray-400"}
                onClick={() => setActiveTab('connect')}
              >
                Start
              </button>
              <button 
                className={activeTab === 'dashboard' ? "py-2 px-4 border-b-2 border-orange-500 text-white" : "py-2 px-4 text-gray-400"}
                onClick={() => setActiveTab('dashboard')}
              >
                Stats
              </button>
              <button 
                className={activeTab === 'test' ? "py-2 px-4 border-b-2 border-orange-500 text-white" : "py-2 px-4 text-gray-400"}
                onClick={() => setActiveTab('test')}
              >
                Simulate
              </button>
            </div>
          </div>
          
          {activeTab === 'connect' && (
            <ConnectTab 
              botStatus={botStatus} 
              onBotStatusChange={handleBotStatusChange}
              wsConnected={wsConnected}
              wsReconnecting={wsReconnecting}
            />
          )}
          
          {activeTab === 'dashboard' && (
            <DashboardTab 
              trades={botStatus.test_mode ? testTrades : trades} 
              balances={balances}
              isTestMode={botStatus.test_mode}
              botStatus={botStatus}
              onReactivatePair={handleReactivatePair}
              onReactivateExchange={handleReactivateExchange}
              onReactivateGlobal={handleReactivateGlobal}
            />
          )}
          
          {activeTab === 'test' && (
            <TestModeTab 
              botStatus={botStatus}
              supportedExchanges={supportedExchanges}
              testTrades={testTrades}
              onStartTest={handleStartTest}
              onStopTest={handleStopTest}
            />
          )}
        </div>
      </main>
      
      {/* Mobile Bottom Navigation */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 bg-gray-800 border-t border-gray-700 z-10">
        <div className="flex justify-between items-center px-4">
          <button 
            className={`py-6 px-6 flex flex-col items-center justify-center flex-1 ${activeTab === 'connect' ? 'text-orange-500' : 'text-gray-400'}`}
            onClick={() => setActiveTab('connect')}
          >
            <span className="text-base font-medium">Start</span>
          </button>
          <button 
            className={`py-6 px-6 flex flex-col items-center justify-center flex-1 ${activeTab === 'dashboard' ? 'text-orange-500' : 'text-gray-400'}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <span className="text-base font-medium">Stats</span>
          </button>
          <button 
            className={`py-6 px-6 flex flex-col items-center justify-center flex-1 ${activeTab === 'test' ? 'text-orange-500' : 'text-gray-400'}`}
            onClick={() => setActiveTab('test')}
          >
            <span className="text-base font-medium">Simulate</span>
          </button>
        </div>
      </div>
      
      <footer className="border-t border-gray-700 py-4 text-center text-sm text-gray-400">
        <div className="container mx-auto px-4">
          <p>© {new Date().getFullYear()} Quantivest - All rights reserved</p>
        </div>
      </footer>
    </div>
  );
}

export default App;
