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

export function connectWebSocket(onMessage: (data: any) => void) {
  const wsUrl = API_URL.replace('http', 'ws') + '/api/ws';
  const socket = new WebSocket(wsUrl);
  
  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch (error) {
      console.error('WebSocket message parsing error:', error);
    }
  };
  
  socket.onclose = () => {
    console.log('WebSocket connection closed');
    setTimeout(() => connectWebSocket(onMessage), 5000);
  };
  
  socket.onerror = (error) => {
    console.error('WebSocket error:', error);
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
