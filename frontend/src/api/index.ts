import { ExchangeCredentials, TestModeSettings, WebSocketMessage } from "../types"; // MODIFICATION: Added WebSocketMessage for clarity

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_URL = API_URL.replace(/^http/, "ws") + "/api/ws";

async function apiRequest(endpoint: string, options: RequestInit = {}) {
  const url = `${API_URL}/api${endpoint}`;
  const defaultHeaders = {
    "Content-Type": "application/json",
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
      let errorData = { detail: `API request failed with status ${response.status}` };
      try {
        errorData = await response.json();
      } catch (e) {
        // Ignore if response is not JSON
      }
      throw new Error(errorData.detail || `API request failed with status ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error(`API request error for ${endpoint}:`, error);
    throw error;
  }
}

// WebSocket connection management
const MAX_RECONNECT_ATTEMPTS = 10;
const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;

export function connectWebSocket(
  onMessage: (data: WebSocketMessage) => void, 
  onConnectionChange: (connected: boolean) => void, 
  onReconnecting: (isReconnecting: boolean) => void
) {
  console.log("Attempting to connect WebSocket at:", WS_URL);
  let socket: WebSocket | null = null;
  let pingIntervalId: number | null = null;
  let reconnectAttempts = 0;
  let reconnectTimeoutId: number | null = null;

  const clearTimers = () => {
    if (pingIntervalId) clearInterval(pingIntervalId);
    pingIntervalId = null;
    if (reconnectTimeoutId) clearTimeout(reconnectTimeoutId);
    reconnectTimeoutId = null;
  };

  const calculateReconnectDelay = () => {
    const delay = Math.min(
      INITIAL_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttempts),
      MAX_RECONNECT_DELAY_MS
    );
    return delay + Math.random() * 1000; // Add jitter
  };

  const connect = () => {
    clearTimers();
    onReconnecting(false); // Reset reconnecting state before new attempt

    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        console.log("WebSocket already open or connecting. Closing existing before reconnecting.");
        socket.onclose = null; // Prevent old onclose from triggering another reconnect cycle
        socket.close();
    }
    
    console.log("Creating new WebSocket connection...");
    socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      console.log("WebSocket connection established.");
      onConnectionChange(true);
      onReconnecting(false);
      reconnectAttempts = 0;
      // Send an initial ping or identification message if required by backend
      socket?.send(JSON.stringify({ type: "ping" })); 
      pingIntervalId = window.setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        } else {
          clearTimers(); // Stop pinging if connection is not open
        }
      }, 25000); // Ping every 25 seconds
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as WebSocketMessage;
        if (data.type === "pong") {
          // console.log("WebSocket pong received.");
          return; // Handle pong silently
        }
        onMessage(data);
      } catch (error) {
        console.error("WebSocket message parsing error:", error, "Raw data:", event.data);
      }
    };

    socket.onclose = (event) => {
      console.log(`WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason}, Clean: ${event.wasClean}`);
      onConnectionChange(false);
      clearTimers();
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        attemptReconnect();
      } else {
        console.error("Max WebSocket reconnection attempts reached.");
        onReconnecting(false);
      }
    };

    socket.onerror = (error) => {
      console.error("WebSocket error:", error);
      // onConnectionChange(false); // onclose will usually be called after an error
      // No need to call attemptReconnect here, onclose will handle it.
    };
  };

  const attemptReconnect = () => {
    reconnectAttempts++;
    const delay = calculateReconnectDelay();
    console.log(`WebSocket: Attempting reconnect ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS} in ${Math.round(delay / 1000)}s...`);
    onReconnecting(true);
    reconnectTimeoutId = window.setTimeout(connect, delay);
  };

  connect(); // Initial connection attempt

  return {
    // socket instance is not directly exposed to avoid misuse
    disconnect: () => {
      console.log("WebSocket: Manual disconnect called.");
      reconnectAttempts = MAX_RECONNECT_ATTEMPTS; // Prevent auto-reconnect on manual disconnect
      clearTimers();
      if (socket) {
        socket.onclose = null; // Prevent onclose from triggering reconnect logic
        socket.close();
        socket = null;
      }
      onConnectionChange(false);
      onReconnecting(false);
    },
    reconnect: () => { // Allow manual trigger of reconnection process
        console.log("WebSocket: Manual reconnect triggered.");
        reconnectAttempts = 0; // Reset attempts for manual reconnect
        if (socket && socket.readyState === WebSocket.OPEN) {
            console.log("WebSocket already open, closing before manual reconnect.");
            socket.close(); // This will trigger the onclose -> attemptReconnect logic
        } else {
            connect(); // If not open, just try to connect
        }
    }
  };
}

// API endpoint definitions
export const exchangeApi = {
  getSupportedExchanges: () => apiRequest("/exchanges"),
  connectExchange: (credentials: ExchangeCredentials) =>
    apiRequest("/exchanges/connect", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),
  disconnectExchange: (exchangeId: string) =>
    apiRequest(`/exchanges/${exchangeId}/disconnect`, { // MODIFICATION: More RESTful endpoint
      method: "POST", // Or DELETE, but POST can also be used for actions
    }),
  getConnectedExchanges: () => apiRequest("/exchanges/connected"),
  getBalances: (forceRefresh: boolean = false) => apiRequest(`/balances?refresh=${forceRefresh}`),
};

export const botApi = {
  getStatus: () => apiRequest("/bot/status"),
  startBot: (isTestMode: boolean, settings?: TestModeSettings) =>
    apiRequest("/bot/start", {
      method: "POST",
      body: JSON.stringify({ mode: isTestMode ? "test" : "live", test_settings: settings }),
    }),
  stopBot: () =>
    apiRequest("/bot/stop", {
      method: "POST",
    }),
  getOpportunities: (limit: number = 20) => apiRequest(`/opportunities?limit=${limit}`),
  getTrades: (limit: number = 50, isTestMode?: boolean) => {
    let url = `/trades?limit=${limit}`;
    if (isTestMode !== undefined) {
      url += `&test_mode=${isTestMode}`;
    }
    return apiRequest(url);
  },
  // getTestBalances: () => apiRequest("/test/balances"), // This might be redundant if general balances include test mode context
  getAlerts: (limit: number = 20) => apiRequest(`/alerts?limit=${limit}`),
  getFailsafeStatus: () => apiRequest("/failsafe/status"), // New endpoint for failsafe status
  reactivatePair: (pair: string) =>
    apiRequest(`/failsafe/reactivate/pair/${pair}`, {
      method: "POST",
    }),
  reactivateExchange: (exchangeId: string) =>
    apiRequest(`/failsafe/reactivate/exchange/${exchangeId}`, {
      method: "POST",
    }),
  reactivateGlobal: () =>
    apiRequest("/failsafe/reactivate/global", {
      method: "POST",
    }),
  reactivateFailsafe: (request: { type: "pair" | "exchange" | "global", entity_name?: string }) => {
    if (request.type === "pair" && request.entity_name) {
      return apiRequest(`/failsafe/reactivate/pair/${request.entity_name}`, { method: "POST" });
    } else if (request.type === "exchange" && request.entity_name) {
      return apiRequest(`/failsafe/reactivate/exchange/${request.entity_name}`, { method: "POST" });
    } else if (request.type === "global") {
      return apiRequest("/failsafe/reactivate/global", { method: "POST" });
    } else {
      throw new Error("Invalid reactivate request");
    }
  },
};

