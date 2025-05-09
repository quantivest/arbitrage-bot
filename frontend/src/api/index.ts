import { ExchangeCredentials, TestModeSettings } from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function apiRequest(endpoint: string, options: RequestInit = {}) {
  const url = `${API_URL}/api${endpoint}`;
  
  const defaultHeaders = {
    'Content-Type': 'application/json',
  };
  
  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  };
  
  try {
    const response = await fetch(url, config);
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `API request failed with status ${response.status}`);
    }
    
    return await response.json();
  } catch (error) {
    console.error('API request error:', error);
    throw error;
  }
}

export function connectWebSocket(onMessage: (data: any) => void, onConnectionChange: (connected: boolean) => void) {
  const wsUrl = API_URL.replace('http', 'ws') + '/api/ws';
  console.log('Connecting to WebSocket at:', wsUrl);
  
  const socket = new WebSocket(wsUrl);
  
  socket.onopen = () => {
    console.log('WebSocket connection established');
    onConnectionChange(true);
    
    socket.send(JSON.stringify({ type: 'ping' }));
    
    const pingInterval = setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'ping' }));
      } else {
        clearInterval(pingInterval);
      }
    }, 30000); // Ping every 30 seconds
  };
  
  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('WebSocket message received:', data);
      
      if (data.type === 'pong') {
        console.log('Received pong from server');
        return;
      }
      
      onMessage(data);
    } catch (error) {
      console.error('WebSocket message parsing error:', error);
    }
  };
  
  socket.onclose = (event) => {
    console.log('WebSocket connection closed:', event.code, event.reason);
    onConnectionChange(false);
  };
  
  socket.onerror = (error) => {
    console.error('WebSocket error:', error);
    onConnectionChange(false);
  };
  
  return socket;
}

export const exchangeApi = {
  getSupportedExchanges: () => apiRequest('/exchanges'),
  
  connectExchange: (credentials: ExchangeCredentials) => 
    apiRequest('/exchanges/connect', {
      method: 'POST',
      body: JSON.stringify(credentials),
    }),
  
  disconnectExchange: (exchangeId: string) => 
    apiRequest(`/exchanges/${exchangeId}`, {
      method: 'DELETE',
    }),
  
  getConnectedExchanges: () => apiRequest('/exchanges/connected'),
  
  getBalances: (refresh: boolean = false) => 
    apiRequest(`/balances?refresh=${refresh}`),
};

export const botApi = {
  getStatus: () => apiRequest('/bot/status'),
  
  startBot: (testMode: boolean = false, testSettings?: TestModeSettings) => 
    apiRequest('/bot/start', {
      method: 'POST',
      body: JSON.stringify({ test_mode: testMode, test_settings: testSettings }),
    }),
  
  stopBot: () => 
    apiRequest('/bot/stop', {
      method: 'POST',
    }),
  
  getOpportunities: (limit: number = 50) => 
    apiRequest(`/opportunities?limit=${limit}`),
  
  getTrades: (limit: number = 50, testMode?: boolean) => {
    let url = `/trades?limit=${limit}`;
    if (testMode !== undefined) {
      url += `&test_mode=${testMode}`;
    }
    return apiRequest(url);
  },
  
  getTestBalances: () => apiRequest('/test/balances'),
  
  getAlerts: (limit: number = 50) => 
    apiRequest(`/alerts?limit=${limit}`),
  
  reactivatePair: (pair: string) => 
    apiRequest(`/reactivate/pair/${pair}`, {
      method: 'POST',
    }),
  
  reactivateExchange: (exchange: string) => 
    apiRequest(`/reactivate/exchange/${exchange}`, {
      method: 'POST',
    }),
  
  reactivateGlobal: () => 
    apiRequest('/reactivate/global', {
      method: 'POST',
    }),
};
