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
    last_update: new Date().toISOString()
  });
  const [supportedExchanges, setSupportedExchanges] = useState<string[]>([]);
  const [balances, setBalances] = useState<ExchangeBalance[]>([]);
  const [trades, setTrades] = useState<ArbitrageTrade[]>([]);
  const [testTrades, setTestTrades] = useState<ArbitrageTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

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
    const socket = connectWebSocket((data) => {
      if (data.bot_status) {
        setBotStatus(data.bot_status);
      }
      
      if (data.recent_trades) {
        const liveTrades = data.recent_trades.filter((trade: ArbitrageTrade) => !trade.is_test);
        const simulatedTrades = data.recent_trades.filter((trade: ArbitrageTrade) => trade.is_test);
        
        if (liveTrades.length > 0) {
          setTrades(prevTrades => {
            const existingIds = new Set(prevTrades.map((t: ArbitrageTrade) => t.id));
            const newTrades = liveTrades.filter((t: ArbitrageTrade) => !existingIds.has(t.id));
            return [...newTrades, ...prevTrades].slice(0, 100); // Keep last 100 trades
          });
        }
        
        if (simulatedTrades.length > 0) {
          setTestTrades(prevTrades => {
            const existingIds = new Set(prevTrades.map((t: ArbitrageTrade) => t.id));
            const newTrades = simulatedTrades.filter((t: ArbitrageTrade) => !existingIds.has(t.id));
            return [...newTrades, ...prevTrades].slice(0, 100); // Keep last 100 trades
          });
        }
      }
      
      setWsConnected(true);
    });
    
    return () => {
      socket.close();
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
    setBotStatus(prev => ({ ...prev, running }));
  };
  
  const handleStartTest = async (settings: TestModeSettings) => {
    try {
      await botApi.startBot(true, settings);
      setBotStatus(prev => ({ ...prev, running: true, test_mode: true }));
      setActiveTab('dashboard');
    } catch (error: any) {
      setError(error.message || 'Failed to start test mode');
    }
  };
  
  const handleStopTest = async () => {
    try {
      await botApi.stopBot();
      setBotStatus(prev => ({ ...prev, running: false, test_mode: false }));
    } catch (error: any) {
      setError(error.message || 'Failed to stop test mode');
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
              <div className={wsConnected ? "h-3 w-3 rounded-full bg-green-500" : "h-3 w-3 rounded-full bg-red-500"}></div>
              <span className="text-sm text-gray-400">
                {wsConnected ? 'Connected' : 'Disconnected'}
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
            />
          )}
          
          {activeTab === 'dashboard' && (
            <DashboardTab 
              trades={botStatus.test_mode ? testTrades : trades} 
              balances={balances}
              isTestMode={botStatus.test_mode}
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
        <div className="flex justify-around">
          <button 
            className={`py-4 px-5 flex flex-col items-center ${activeTab === 'connect' ? 'text-orange-500' : 'text-gray-400'}`}
            onClick={() => setActiveTab('connect')}
          >
            <span className="text-base font-medium">Connect & Run</span>
          </button>
          <button 
            className={`py-4 px-5 flex flex-col items-center ${activeTab === 'dashboard' ? 'text-orange-500' : 'text-gray-400'}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <span className="text-base font-medium">Stats</span>
          </button>
          <button 
            className={`py-4 px-5 flex flex-col items-center ${activeTab === 'test' ? 'text-orange-500' : 'text-gray-400'}`}
            onClick={() => setActiveTab('test')}
          >
            <span className="text-base font-medium">Test Mode</span>
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
