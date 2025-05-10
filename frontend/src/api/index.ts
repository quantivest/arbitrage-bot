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

const MAX_RECONNECT_ATTEMPTS = 10;
const INITIAL_RECONNECT_DELAY = 500;
const MAX_RECONNECT_DELAY = 30000;

export function connectWebSocket(onMessage: (data: any) => void, onConnectionChange: (connected: boolean) => void, onReconnecting: (isReconnecting: boolean) => void) {
  const wsUrl = API_URL.replace('http', 'ws') + '/api/ws';
  console.log('Connecting to WebSocket at:', wsUrl);
  
  let socket: WebSocket | null = null;
  let pingInterval: number | null = null;
  let reconnectAttempts = 0;
  let reconnectTimeout: number | null = null;
  
  const clearTimers = () => {
    if (pingInterval) {
      clearInterval(pingInterval);
      pingInterval = null;
    }
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }
  };
  
  const getReconnectDelay = () => {
    const delay = Math.min(
      INITIAL_RECONNECT_DELAY * Math.pow(2, reconnectAttempts),
      MAX_RECONNECT_DELAY
    );
    return delay + (Math.random() * 1000);
  };
  
  const connect = () => {
    clearTimers();
    
    if (socket) {
      socket.onclose = null;
      socket.onerror = null;
      socket.onopen = null;
      socket.onmessage = null;
      socket.close();
    }
    
    socket = new WebSocket(wsUrl);
    
    socket.onopen = () => {
      console.log('WebSocket connection established');
      onConnectionChange(true);
      onReconnecting(false);
      reconnectAttempts = 0;
      
      socket?.send(JSON.stringify({ type: 'ping' }));
      
      pingInterval = window.setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'ping' }));
        } else {
          if (pingInterval) {
            clearInterval(pingInterval);
            pingInterval = null;
          }
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
      attemptReconnect();
    };
    
    socket.onerror = (error) => {
      console.error('WebSocket error:', error);
      onConnectionChange(false);
    };
  };
  
  const attemptReconnect = () => {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.log('Maximum reconnection attempts reached');
      onReconnecting(false);
      return;
    }
    
    reconnectAttempts++;
    const delay = getReconnectDelay();
    
    console.log(`Attempting to reconnect (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}) in ${Math.round(delay / 1000)}s`);
    onReconnecting(true);
    
    reconnectTimeout = window.setTimeout(() => {
      connect();
    }, delay);
  };
  
  connect();
  
  return {
    socket,
    disconnect: () => {
      clearTimers();
      if (socket) {
        socket.close();
        socket = null;
      }
    },
    reconnect: () => {
      reconnectAttempts = 0;
      connect();
    }
  };
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
