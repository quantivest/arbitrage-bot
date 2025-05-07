import { useState, useEffect } from 'react';
import { Button } from './ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Alert, AlertDescription } from './ui/alert';
import { exchangeApi, botApi } from '../api';
import { BotStatus } from '../types';
import { AlertCircle, CheckCircle } from 'lucide-react';

interface ConnectTabProps {
  botStatus: BotStatus;
  onBotStatusChange: (running: boolean) => void;
}

export default function ConnectTab({ botStatus, onBotStatusChange }: ConnectTabProps) {
  const [supportedExchanges, setSupportedExchanges] = useState<string[]>([]);
  const [selectedExchange, setSelectedExchange] = useState<string>('');
  const [apiKey, setApiKey] = useState<string>('');
  const [apiSecret, setApiSecret] = useState<string>('');
  const [additionalParams, setAdditionalParams] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    const fetchExchanges = async () => {
      try {
        const response = await exchangeApi.getSupportedExchanges();
        setSupportedExchanges(response.exchanges);
        if (response.exchanges.length > 0) {
          setSelectedExchange(response.exchanges[0]);
        }
      } catch (error) {
        setError('Failed to fetch supported exchanges');
      }
    };

    fetchExchanges();
  }, []);

  const handleConnect = async () => {
    try {
      setError(null);
      setSuccess(null);

      if (!selectedExchange) {
        setError('Please select an exchange');
        return;
      }

      if (!apiKey || !apiSecret) {
        setError('API key and secret are required');
        return;
      }

      let parsedParams = {};
      if (additionalParams) {
        try {
          parsedParams = JSON.parse(additionalParams);
        } catch (e) {
          setError('Invalid additional parameters format. Use valid JSON.');
          return;
        }
      }

      await exchangeApi.connectExchange({
        exchange: selectedExchange,
        api_key: apiKey,
        api_secret: apiSecret,
        additional_params: parsedParams,
      });

      setSuccess(`Successfully connected to ${selectedExchange}`);
      
      setApiKey('');
      setApiSecret('');
      setAdditionalParams('');
    } catch (error: any) {
      setError(error.message || 'Failed to connect to exchange');
    }
  };

  const handleStartStop = async () => {
    try {
      setError(null);
      
      if (botStatus.running) {
        await botApi.stopBot();
        onBotStatusChange(false);
      } else {
        if (botStatus.connected_exchanges.length < 2) {
          setError('Minimum 2 exchanges to start this bot');
          return;
        }
        
        await botApi.startBot(false);
        onBotStatusChange(true);
      }
    } catch (error: any) {
      setError(error.message || 'Failed to start/stop bot');
    }
  };

  return (
    <div className="container mx-auto py-6">
      <h2 className="text-2xl font-bold mb-6 md:text-left text-center">Connect & Run</h2>
      
      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      
      {success && (
        <Alert className="mb-4 bg-green-100 border-green-400">
          <CheckCircle className="h-4 w-4 text-green-600" />
          <AlertDescription className="text-green-600">{success}</AlertDescription>
        </Alert>
      )}
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Connect Exchange</CardTitle>
            <CardDescription>
              Add your exchange API credentials to connect
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="exchange">Exchange</Label>
                <select 
                  id="exchange"
                  className="w-full p-2 border border-[#4A4A4F] rounded-md bg-[#2C2C2E] text-white"
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
              
              <div className="space-y-2">
                <Label htmlFor="apiKey">API Key</Label>
                <Input
                  id="apiKey"
                  type="text"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Enter your API key"
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="apiSecret">API Secret</Label>
                <Input
                  id="apiSecret"
                  type="password"
                  value={apiSecret}
                  onChange={(e) => setApiSecret(e.target.value)}
                  placeholder="Enter your API secret"
                />
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="additionalParams">Additional Parameters (JSON, optional)</Label>
                <Input
                  id="additionalParams"
                  type="text"
                  value={additionalParams}
                  onChange={(e) => setAdditionalParams(e.target.value)}
                  placeholder='{"param1": "value1"}'
                />
              </div>
            </div>
          </CardContent>
          <CardFooter>
            <Button onClick={handleConnect} className="w-full">
              Connect
            </Button>
          </CardFooter>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Connected Exchanges</CardTitle>
            <CardDescription>
              Manage your connected exchanges
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {botStatus.connected_exchanges.length === 0 ? (
                <div className="text-center py-8 text-white">
                  No exchanges connected
                </div>
              ) : (
                <ul className="space-y-2">
                  {botStatus.connected_exchanges.map((exchange) => (
                    <li key={exchange} className="flex justify-between items-center p-2 border border-[#4A4A4F] bg-[#2C2C2E] text-white rounded-md">
                      <span className="font-medium">
                        {exchange.charAt(0).toUpperCase() + exchange.slice(1)}
                      </span>
                      <div className="flex items-center">
                        <CheckCircle className="h-4 w-4 text-green-600 mr-2" />
                        <span className="text-green-600 text-sm">Connected</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              
              {botStatus.connected_exchanges.length < 2 && (
                <Alert className="mt-4">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    Minimum 2 exchanges to start this bot
                  </AlertDescription>
                </Alert>
              )}
            </div>
          </CardContent>
          <CardFooter>
            <Button 
              onClick={handleStartStop}
              className={`w-full ${botStatus.running ? 'bg-red-600 hover:bg-red-700' : 'bg-gradient-to-r from-orange-500 to-red-600 hover:from-orange-600 hover:to-red-700'}`}
              disabled={botStatus.connected_exchanges.length < 2}
            >
              {botStatus.running ? 'Stop Bot' : 'Start Bot'}
            </Button>
          </CardFooter>
        </Card>
      </div>
      
      <div className="mt-6 flex justify-center">
        <div className="flex items-center space-x-2">
          <div className={`h-4 w-4 rounded-full ${botStatus.running ? 'bg-green-500' : 'bg-red-500'}`}></div>
          <span className="font-medium">
            Bot Status: {botStatus.running ? 'Running' : 'Stopped'}
          </span>
        </div>
      </div>
    </div>
  );
}
