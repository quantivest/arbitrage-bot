import { useState, useEffect } from 'react';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Slider } from './ui/slider';
import { Label } from './ui/label';
import { Alert, AlertDescription } from './ui/alert';
import { ArbitrageTrade, BotStatus, TestModeSettings } from '../types';
import { AlertCircle, Play, Square } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from 'recharts';

interface TestModeTabProps {
  botStatus: BotStatus;
  supportedExchanges: string[];
  testTrades: ArbitrageTrade[];
  onStartTest: (settings: TestModeSettings) => void;
  onStopTest: () => void;
}

export default function TestModeTab({ 
  botStatus, 
  supportedExchanges, 
  testTrades, 
  onStartTest, 
  onStopTest 
}: TestModeTabProps) {
  const [assetCapital, setAssetCapital] = useState<number>(50);
  const [bufferPercentage, setBufferPercentage] = useState<number>(0.01);
  const [usdtCapital, setUsdtCapital] = useState<number>(50);
  const [selectedExchanges, setSelectedExchanges] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [profitChartData, setProfitChartData] = useState<any[]>([]);
  const [winRateData, setWinRateData] = useState<any[]>([]);
  
  useEffect(() => {
    if (supportedExchanges.length > 0 && selectedExchanges.length === 0) {
      setSelectedExchanges(supportedExchanges.slice(0, Math.min(2, supportedExchanges.length)));
    }
  }, [supportedExchanges]);
  
  useEffect(() => {
    const profitData = testTrades.slice(0, 20).map(trade => ({
      time: new Date(trade.timestamp).toLocaleTimeString(),
      profit: trade.profit,
      profitPercentage: trade.profit_percentage,
    })).reverse();
    setProfitChartData(profitData);
    
    if (testTrades.length > 0) {
      const winningTrades = testTrades.filter(trade => trade.profit > 0).length;
      const winRate = (winningTrades / testTrades.length) * 100;
      
      setWinRateData([
        { name: 'Win', value: winRate },
        { name: 'Loss', value: 100 - winRate },
      ]);
    }
  }, [testTrades]);
  
  const handleExchangeToggle = (exchange: string) => {
    if (selectedExchanges.includes(exchange)) {
      setSelectedExchanges(selectedExchanges.filter((e: string) => e !== exchange));
    } else {
      setSelectedExchanges([...selectedExchanges, exchange]);
    }
  };
  
  const handleStartTest = async () => {
    try {
      setError(null);
      
      if (selectedExchanges.length < 2) {
        setError('Please select at least 2 exchanges for testing');
        return;
      }
      
      const capital_per_pair = {};
      const tradingPairs = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "DOGE/USDT",
        "XRP/USDT", "DOT/USDT", "LTC/USDT", "LINK/USDT", "MATIC/USDT"
      ];
      
      tradingPairs.forEach(pair => {
        capital_per_pair[pair] = assetCapital;
      });
      
      const testSettings: TestModeSettings = {
        enabled: true,
        capital_per_pair: capital_per_pair,
        buffer_percentage: bufferPercentage / 100, // Convert from percentage to decimal
        exchanges: selectedExchanges,
        usdt_cap: usdtCapital,
        asset_cap: assetCapital,
      };
      
      onStartTest(testSettings);
    } catch (error: any) {
      setError(error.message || 'Failed to start test mode');
    }
  };
  
  
  return (
    <div className="container mx-auto py-6">
      <h2 className="text-2xl font-bold mb-6 md:text-left text-center">Test Mode</h2>
      
      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <Card>
          <CardHeader>
            <CardTitle>Test Settings</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-6">
              {/* Mobile collapsible slider section */}
              <div className="md:hidden">
                <Button
                  variant="outline"
                  className="w-full flex justify-between items-center mb-4 bg-black text-gray-400 border-gray-700"
                  onClick={() => document.getElementById('mobile-sliders')?.classList.toggle('hidden')}
                >
                  <span className="font-medium">Sliders</span>
                  <span className="text-sm">▼</span>
                </Button>
                
                <div id="mobile-sliders" className="space-y-6 hidden">
                  <div className="space-y-4">
                    <Label>USDT Capital (per exchange): ${usdtCapital}</Label>
                    <div className="flex items-center space-x-2">
                      <Slider
                        value={[usdtCapital]}
                        min={50}
                        max={7500}
                        step={50}
                        onValueChange={(value) => setUsdtCapital(value[0])}
                        disabled={botStatus.test_mode}
                        className="flex-grow"
                      />
                      <input
                        type="number"
                        min={50}
                        max={7500}
                        value={usdtCapital}
                        onChange={(e) => setUsdtCapital(Number(e.target.value))}
                        className="w-20 bg-[#2C2C2E] border border-gray-700 rounded px-2 py-1 text-white"
                        disabled={botStatus.test_mode}
                      />
                    </div>
                  </div>
                  
                  <div className="space-y-4">
                    <Label>Asset Capital (per pair): ${assetCapital}</Label>
                    <div className="flex items-center space-x-2">
                      <Slider
                        value={[assetCapital]}
                        min={10}
                        max={750}
                        step={10}
                        onValueChange={(value) => setAssetCapital(value[0])}
                        disabled={botStatus.test_mode}
                        className="flex-grow"
                      />
                      <input
                        type="number"
                        min={10}
                        max={750}
                        value={assetCapital}
                        onChange={(e) => setAssetCapital(Number(e.target.value))}
                        className="w-20 bg-[#2C2C2E] border border-gray-700 rounded px-2 py-1 text-white"
                        disabled={botStatus.test_mode}
                      />
                    </div>
                  </div>
                  
                  <div className="space-y-4">
                    <Label>Buffer Percentage: {bufferPercentage.toFixed(4)}%</Label>
                    <div className="flex items-center space-x-2">
                      <Slider
                        value={[bufferPercentage]}
                        min={0}
                        max={1}
                        step={0.0001}
                        onValueChange={(value) => setBufferPercentage(value[0])}
                        disabled={botStatus.test_mode}
                        className="flex-grow"
                      />
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.0001}
                        value={bufferPercentage}
                        onChange={(e) => setBufferPercentage(Number(e.target.value))}
                        className="w-20 bg-[#2C2C2E] border border-gray-700 rounded px-2 py-1 text-white"
                        disabled={botStatus.test_mode}
                      />
                    </div>
                  </div>
                </div>
              </div>
              
              {/* Desktop slider section (non-collapsible) */}
              <div className="hidden md:block space-y-6">
                <div className="space-y-4">
                  <Label>USDT Capital (per exchange): ${usdtCapital}</Label>
                  <div className="flex items-center space-x-2">
                    <Slider
                      value={[usdtCapital]}
                      min={50}
                      max={7500}
                      step={50}
                      onValueChange={(value) => setUsdtCapital(value[0])}
                      disabled={botStatus.test_mode}
                      className="flex-grow"
                    />
                    <input
                      type="number"
                      min={50}
                      max={7500}
                      value={usdtCapital}
                      onChange={(e) => setUsdtCapital(Number(e.target.value))}
                      className="w-20 bg-[#2C2C2E] border border-gray-700 rounded px-2 py-1 text-white"
                      disabled={botStatus.test_mode}
                    />
                  </div>
                </div>
                
                <div className="space-y-4">
                  <Label>Asset Capital (per pair): ${assetCapital}</Label>
                  <div className="flex items-center space-x-2">
                    <Slider
                      value={[assetCapital]}
                      min={10}
                      max={750}
                      step={10}
                      onValueChange={(value) => setAssetCapital(value[0])}
                      disabled={botStatus.test_mode}
                      className="flex-grow"
                    />
                    <input
                      type="number"
                      min={10}
                      max={750}
                      value={assetCapital}
                      onChange={(e) => setAssetCapital(Number(e.target.value))}
                      className="w-20 bg-[#2C2C2E] border border-gray-700 rounded px-2 py-1 text-white"
                      disabled={botStatus.test_mode}
                    />
                  </div>
                </div>
                
                <div className="space-y-4">
                  <Label>Buffer Percentage: {bufferPercentage.toFixed(4)}%</Label>
                  <div className="flex items-center space-x-2">
                    <Slider
                      value={[bufferPercentage]}
                      min={0}
                      max={1}
                      step={0.0001}
                      onValueChange={(value) => setBufferPercentage(value[0])}
                      disabled={botStatus.test_mode}
                      className="flex-grow"
                    />
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.0001}
                      value={bufferPercentage}
                      onChange={(e) => setBufferPercentage(Number(e.target.value))}
                      className="w-20 bg-[#2C2C2E] border border-gray-700 rounded px-2 py-1 text-white"
                      disabled={botStatus.test_mode}
                    />
                  </div>
                </div>
              </div>
              
              <div className="space-y-4">
                <Label>Select Exchanges (min 2)</Label>
                <div className="grid grid-cols-2 gap-2">
                  {supportedExchanges.map((exchange) => (
                    <Button
                      key={exchange}
                      variant={selectedExchanges.includes(exchange) ? "default" : "outline"}
                      onClick={() => handleExchangeToggle(exchange)}
                      className={`justify-start ${!selectedExchanges.includes(exchange) ? "bg-[#2C2C2E] text-white" : ""}`}
                      disabled={botStatus.test_mode}
                    >
                      {exchange.charAt(0).toUpperCase() + exchange.slice(1)}
                    </Button>
                  ))}
                </div>
              </div>
              
              <Button
                onClick={botStatus.test_mode ? onStopTest : handleStartTest}
                className={`w-full ${botStatus.test_mode ? 'bg-red-600 hover:bg-red-700' : 'bg-gradient-to-r from-orange-500 to-red-600 hover:from-orange-600 hover:to-red-700'}`}
                disabled={selectedExchanges.length < 2}
              >
                {botStatus.test_mode ? (
                  <>
                    <Square className="mr-2 h-4 w-4" />
                    Stop Simulation
                  </>
                ) : (
                  <>
                    <Play className="mr-2 h-4 w-4" />
                    Start Simulation
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Test Results</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium">Total Test Trades</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">{testTrades.length}</div>
                  </CardContent>
                </Card>
                
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium">Total Profit</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">
                      ${testTrades.reduce((sum, trade) => sum + trade.profit, 0).toFixed(2)}
                    </div>
                  </CardContent>
                </Card>
              </div>
              
              <div className="h-60">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={profitChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="time" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="profit" stroke="#ff4500" activeDot={{ r: 8 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              
              <div className="h-60">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={winRateData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="value" fill="#ff8c00" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
      
      <Card>
        <CardHeader>
          <CardTitle>Simulated Trade Logs</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Desktop view - horizontal table */}
          <div className="overflow-x-auto hidden md:block">
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-[#4A4A4F]">
                  <th className="text-left py-2 text-white">Time</th>
                  <th className="text-left py-2 text-white">Pair</th>
                  <th className="text-left py-2 text-white">Buy Exchange</th>
                  <th className="text-left py-2 text-white">Sell Exchange</th>
                  <th className="text-right py-2 text-white">Spread %</th>
                  <th className="text-right py-2 text-white">Amount</th>
                  <th className="text-right py-2 text-white">Profit</th>
                </tr>
              </thead>
              <tbody>
                {testTrades.slice(0, 10).map((trade) => (
                  <tr key={trade.id} className="border-b border-[#4A4A4F]">
                    <td className="py-2 text-white">{new Date(trade.timestamp).toLocaleTimeString()}</td>
                    <td className="py-2 text-white">{trade.buy_trade.symbol}</td>
                    <td className="py-2 text-white">{trade.buy_trade.exchange}</td>
                    <td className="py-2 text-white">{trade.sell_trade.exchange}</td>
                    <td className={`text-right py-2 ${trade.profit_percentage > 0 ? 'text-green-500' : 'text-red-500'}`}>
                      {trade.profit_percentage.toFixed(2)}%
                    </td>
                    <td className="text-right py-2 text-white">{trade.buy_trade.amount.toFixed(6)}</td>
                    <td className={`text-right py-2 ${trade.profit > 0 ? 'text-green-500' : 'text-red-500'}`}>
                      ${trade.profit.toFixed(2)}
                    </td>
                  </tr>
                ))}
                {testTrades.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-4 text-center text-white">
                      No test trades executed yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          
          {/* Mobile view - vertical cards */}
          <div className="md:hidden space-y-4">
            {testTrades.slice(0, 10).map((trade) => (
              <div key={trade.id} className="p-3 border border-[#4A4A4F] rounded-md">
                <div className="grid grid-cols-2 gap-2 mb-2">
                  <div className="text-gray-400">Time:</div>
                  <div className="text-white">{new Date(trade.timestamp).toLocaleTimeString()}</div>
                  <div className="text-gray-400">Pair:</div>
                  <div className="text-white">{trade.buy_trade.symbol}</div>
                </div>
                <div className="grid grid-cols-2 gap-2 mb-2">
                  <div className="text-gray-400">Buy Exchange:</div>
                  <div className="text-white">{trade.buy_trade.exchange}</div>
                  <div className="text-gray-400">Sell Exchange:</div>
                  <div className="text-white">{trade.sell_trade.exchange}</div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="text-gray-400">Spread %:</div>
                  <div className={`text-right ${trade.profit_percentage > 0 ? 'text-green-500' : 'text-red-500'}`}>
                    {trade.profit_percentage.toFixed(2)}%
                  </div>
                  <div className="text-gray-400">Amount:</div>
                  <div className="text-right text-white">{trade.buy_trade.amount.toFixed(6)}</div>
                  <div className="text-gray-400">Profit:</div>
                  <div className={`text-right ${trade.profit > 0 ? 'text-green-500' : 'text-red-500'}`}>
                    ${trade.profit.toFixed(2)}
                  </div>
                </div>
              </div>
            ))}
            {testTrades.length === 0 && (
              <div className="py-4 text-center text-white">
                No test trades executed yet
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
