import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { ArbitrageTrade, ExchangeBalance, AlertType, BotStatus } from '../types';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from 'recharts';
import { formatDistanceToNow } from 'date-fns';
import { Button } from './ui/button';
import { AlertCircle, RefreshCw } from 'lucide-react';

interface DashboardTabProps {
  trades: ArbitrageTrade[];
  balances: ExchangeBalance[];
  isTestMode: boolean;
  botStatus: BotStatus;
  onReactivatePair: (pair: string) => void;
  onReactivateExchange: (exchange: string) => void;
  onReactivateGlobal: () => void;
}

export default function DashboardTab({ trades, balances, isTestMode, botStatus, onReactivatePair, onReactivateExchange, onReactivateGlobal }: DashboardTabProps) {
  const [pnlChartData, setPnlChartData] = useState<any[]>([]);
  const [spreadChartData, setSpreadChartData] = useState<any[]>([]);
  const [volumeChartData, setVolumeChartData] = useState<any[]>([]);
  
  useEffect(() => {
    const pnlData = trades.slice(0, 20).map(trade => ({
      time: new Date(trade.timestamp).toLocaleTimeString(),
      profit: trade.profit,
    })).reverse();
    setPnlChartData(pnlData);
    
    const spreadData = trades.slice(0, 20).map(trade => ({
      time: new Date(trade.timestamp).toLocaleTimeString(),
      spread: trade.profit_percentage,
    })).reverse();
    setSpreadChartData(spreadData);
    
    const volumeBySymbol: Record<string, number> = {};
    trades.forEach(trade => {
      const symbol = trade.buy_trade.symbol;
      volumeBySymbol[symbol] = (volumeBySymbol[symbol] || 0) + trade.buy_trade.amount;
    });
    
    const volumeData = Object.entries(volumeBySymbol).map(([symbol, volume]) => ({
      symbol,
      volume,
    }));
    setVolumeChartData(volumeData);
  }, [trades]);
  
  const totalTrades = trades.length;
  const totalProfit = trades.reduce((sum, trade) => sum + trade.profit, 0);
  const averageSpread = trades.length > 0 
    ? trades.reduce((sum, trade) => sum + trade.profit_percentage, 0) / trades.length 
    : 0;
  
  return (
    <div className="container mx-auto py-6">
      <h2 className="text-2xl font-bold mb-6 md:text-left text-center">Live Stats {isTestMode ? '(Test Mode)' : ''}</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Total Trades</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalTrades}</div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Total Profit</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalProfit.toFixed(2)}</div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Average Spread</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{averageSpread.toFixed(2)}%</div>
          </CardContent>
        </Card>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Trades Blocked</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{botStatus?.trades_blocked || 0}</div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Failsafes Triggered</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{botStatus?.failsafes_triggered || 0}</div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">System Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${botStatus?.failsafe_status?.global_halt ? 'text-red-500' : 'text-green-500'}`}>
              {botStatus?.failsafe_status?.global_halt ? 'HALTED' : 'ACTIVE'}
            </div>
          </CardContent>
        </Card>
      </div>
      
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Alerts & System Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-60 overflow-y-auto bg-gray-800 rounded-md">
            {botStatus?.alerts && botStatus.alerts.length > 0 ? (
              <div className="space-y-2 p-2">
                {botStatus.alerts.map((alert, index) => (
                  <div 
                    key={index} 
                    className={`p-3 rounded-md ${
                      alert.can_reactivate ? 'bg-red-900/30' : 'bg-green-900/30'
                    }`}
                  >
                    <div className="flex justify-between items-start mb-1">
                      <div className="flex items-center">
                        <AlertCircle className="h-4 w-4 mr-2 text-white" />
                        <span className="text-white font-medium">
                          {alert.type === 'pair_disabled' && 'Pair Disabled'}
                          {alert.type === 'exchange_disabled' && 'Exchange Disabled'}
                          {alert.type === 'global_halt' && 'Global Halt'}
                          {alert.type === 'partial_fill' && 'Partial Fill'}
                          {alert.type === 'trade_error' && 'Trade Error'}
                        </span>
                      </div>
                      <span className="text-xs text-gray-400">
                        {new Date(alert.timestamp).toLocaleString()}
                      </span>
                    </div>
                    <p className="text-white text-sm mb-2">{alert.message}</p>
                    {alert.can_reactivate && (
                      <div className="flex justify-end">
                        <Button 
                          size="sm" 
                          className="bg-green-700 hover:bg-green-600 text-white"
                          onClick={() => {
                            if (alert.type === 'pair_disabled' && alert.entity) {
                              onReactivatePair(alert.entity);
                            } else if (alert.type === 'exchange_disabled' && alert.entity) {
                              onReactivateExchange(alert.entity);
                            } else if (alert.type === 'global_halt') {
                              onReactivateGlobal();
                            }
                          }}
                        >
                          <RefreshCw className="h-3 w-3 mr-1" />
                          Reactivate
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-4 text-center text-white">
                No alerts at this time. System operating normally.
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <Card>
          <CardHeader>
            <CardTitle>PnL Performance</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={pnlChartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="profit" stroke="#ff4500" activeDot={{ r: 8 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Spread Over Time</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={spreadChartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="spread" stroke="#ff8c00" activeDot={{ r: 8 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <Card>
          <CardHeader>
            <CardTitle>Trade Volume</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={volumeChartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="symbol" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="volume" fill="#ff6347" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Exchange Balances</CardTitle>
          </CardHeader>
          <CardContent>
            {/* Desktop view - horizontal table */}
            <div className="overflow-x-auto hidden md:block">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-[#4A4A4F]">
                    <th className="text-left py-2 text-white">Exchange</th>
                    <th className="text-right py-2 text-white">BTC</th>
                    <th className="text-right py-2 text-white">ETH</th>
                    <th className="text-right py-2 text-white">SOL</th>
                    <th className="text-right py-2 text-white">USDT</th>
                  </tr>
                </thead>
                <tbody>
                  {balances.map((balance) => (
                    <tr key={balance.exchange} className="border-b border-[#4A4A4F]">
                      <td className="py-2 text-white">{balance.exchange}</td>
                      <td className="text-right py-2 text-white">{balance.balances.BTC?.total.toFixed(6) || '0.000000'}</td>
                      <td className="text-right py-2 text-white">{balance.balances.ETH?.total.toFixed(6) || '0.000000'}</td>
                      <td className="text-right py-2 text-white">{balance.balances.SOL?.total.toFixed(6) || '0.000000'}</td>
                      <td className="text-right py-2 text-white">{balance.balances.USDT?.total.toFixed(2) || '0.00'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            {/* Mobile view - vertical cards */}
            <div className="md:hidden space-y-4">
              {balances.map((balance) => (
                <div key={balance.exchange} className="p-3 border border-[#4A4A4F] rounded-md">
                  <div className="font-medium text-white mb-2">{balance.exchange}</div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="text-gray-400">BTC:</div>
                    <div className="text-right text-white">{balance.balances.BTC?.total.toFixed(6) || '0.000000'}</div>
                    <div className="text-gray-400">ETH:</div>
                    <div className="text-right text-white">{balance.balances.ETH?.total.toFixed(6) || '0.000000'}</div>
                    <div className="text-gray-400">SOL:</div>
                    <div className="text-right text-white">{balance.balances.SOL?.total.toFixed(6) || '0.000000'}</div>
                    <div className="text-gray-400">USDT:</div>
                    <div className="text-right text-white">{balance.balances.USDT?.total.toFixed(2) || '0.00'}</div>
                  </div>
                </div>
              ))}
              {balances.length === 0 && (
                <div className="text-center py-4 text-white">No balances available</div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
      
      <Card>
        <CardHeader>
          <CardTitle>Live Trade Feed</CardTitle>
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
                  <th className="text-right py-2 text-white">Profit %</th>
                  <th className="text-right py-2 text-white">PnL</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice(0, 10).map((trade) => (
                  <tr key={trade.id} className="border-b border-[#4A4A4F]">
                    <td className="py-2 text-white">{formatDistanceToNow(new Date(trade.timestamp))} ago</td>
                    <td className="py-2 text-white">{trade.buy_trade.symbol}</td>
                    <td className="py-2 text-white">{trade.buy_trade.exchange}</td>
                    <td className="py-2 text-white">{trade.sell_trade.exchange}</td>
                    <td className={`text-right py-2 ${trade.profit_percentage > 0 ? 'text-green-500' : 'text-red-500'}`}>
                      {trade.profit_percentage.toFixed(2)}%
                    </td>
                    <td className={`text-right py-2 ${trade.profit > 0 ? 'text-green-500' : 'text-red-500'}`}>
                      ${trade.profit.toFixed(2)}
                    </td>
                  </tr>
                ))}
                {trades.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-4 text-center text-white">
                      No trades executed yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          
          {/* Mobile view - vertical cards */}
          <div className="md:hidden space-y-4">
            {trades.slice(0, 10).map((trade) => (
              <div key={trade.id} className="p-3 border border-[#4A4A4F] rounded-md">
                <div className="grid grid-cols-2 gap-2 mb-2">
                  <div className="text-gray-400">Time:</div>
                  <div className="text-white">{formatDistanceToNow(new Date(trade.timestamp))} ago</div>
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
                  <div className="text-gray-400">Profit %:</div>
                  <div className={`text-right ${trade.profit_percentage > 0 ? 'text-green-500' : 'text-red-500'}`}>
                    {trade.profit_percentage.toFixed(2)}%
                  </div>
                  <div className="text-gray-400">PnL:</div>
                  <div className={`text-right ${trade.profit > 0 ? 'text-green-500' : 'text-red-500'}`}>
                    ${trade.profit.toFixed(2)}
                  </div>
                </div>
              </div>
            ))}
            {trades.length === 0 && (
              <div className="py-4 text-center text-white">
                No trades executed yet
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
