import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

const WEBSOCKET_URL = 'ws://localhost:8000/ws'; 
const MAX_IMAGES_TO_DISPLAY = 20; 




function App() {
  const [receivedImages, setReceivedImages] = useState([]);
  const [connectionStatus, setConnectionStatus] = useState('Connecting...');
  const [activeTool, setActiveTool] = useState('NDVI');
  const websocket = useRef(null);
  const isMounted = useRef(true);
  
  const connectWebSocket = useCallback(() => {
    console.log('Attempting to connect WebSocket...');
    setConnectionStatus('Connecting...');
    websocket.current = new WebSocket(WEBSOCKET_URL);

    websocket.current.onopen = () => {
      if (!isMounted.current) return; 
      console.log('WebSocket Connected');
      setConnectionStatus('Connected');
    };

    websocket.current.onclose = (event) => {
      console.log(`WebSocket Disconnected: ${event.code} ${event.reason}`);
      websocket.current = null; 
      if (!isMounted.current) return; 

      setConnectionStatus(`Disconnected (Code: ${event.code}). Reconnecting...`);
      
      setTimeout(() => {
        if (isMounted.current) { 
             connectWebSocket(); 
        }
      }, Math.min(30000, 5000)); 
    };

    websocket.current.onerror = (error) => {
      console.error('WebSocket Error:', error);
      if (!isMounted.current) return;
      setConnectionStatus('Connection Error');
      
      websocket.current?.close(); 
    };

    websocket.current.onmessage = (event) => {
      if (!isMounted.current) return; 
      try {
        const message = JSON.parse(event.data);
        
        if (message.uav_id && message.timestamp) {
          setReceivedImages(
            [
              { 
                imageId: `UAV-${message.uav_id}-${message.timestamp}`,
                metadata: message.metadata,
                rgbUrl: message.rgb_url,
                ndviUrl: message.ndvi_url
              },
            ].slice(0, MAX_IMAGES_TO_DISPLAY) 
          );
        } else {
          console.warn('Received incomplete message:', message);
        }
      } catch (error) {
        console.error('Failed to parse message or invalid message format:', error);
      }
    };
  }, []); 

  useEffect(() => {
    isMounted.current = true; 
    connectWebSocket(); 
    
    return () => {
      isMounted.current = false; 
      console.log('Cleaning up WebSocket connection...');
      if (websocket.current) {
        websocket.current.onclose = null; 
        websocket.current.onerror = null;
        websocket.current.onmessage = null;
        websocket.current.onopen = null;
        if(websocket.current.readyState === WebSocket.OPEN) {
             websocket.current.close(1000, 'Component unmounting');
             console.log('WebSocket connection closed.');
        }
        websocket.current = null; 
      }
    };
  }, [connectWebSocket]); 

  const getConnectionStatusClass = () => {
    switch(connectionStatus) {
      case 'Connected': return 'status-dot status-connected';
      case 'Connection Error': return 'status-dot status-error';
      default: return connectionStatus.includes('Disconnected') ? 'status-dot status-error' : 'status-dot status-connecting';
    }
  };

  const handleToolSelect = (tool) => {
    setActiveTool(tool);
  };

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="sidebar-header">
          
          {/* Enhanced Connection Status */}
          <div className="connection-status-container">
            <span className="connection-label">Connection:</span>
            <div className="connection-indicator">
              <div className={getConnectionStatusClass()}></div>
              <span className="connection-text">{connectionStatus}</span>
            </div>
          </div>
        </div>

        {/* Sidebar Navigation */}
        <div className="sidebar-content">
          <div className="sidebar-section">
            <h3 className="section-title">Vegetation index:</h3>
            <ul className="tool-list">
              {['NDVI', 'RGB'].map((tool) => (
                <li key={tool}>
                  <button
                    onClick={() => handleToolSelect(tool)}
                    className={`tool-button ${activeTool === tool ? 'active' : ''}`}
                  >
                    {tool}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="sidebar-section">
            <h3 className="section-title">Machine learning:</h3>
            <ul className="tool-list">
              <li>
                <button
                  onClick={() => handleToolSelect('K-means')}
                  className={`tool-button ${activeTool === 'K-means' ? 'active' : ''}`}
                >
                  K-means
                </button>
              </li>
              <li>
                <button
                  onClick={() => handleToolSelect('U-net (with NDVI)')}
                  className={`tool-button ${activeTool === 'U-net (with NDVI)' ? 'active' : ''}`}
                >
                  U-net (with NDVI)
                </button>
              </li>
              <li>
                <button
                  onClick={() => handleToolSelect('U-net (With RGBN)')}
                  className={`tool-button ${activeTool === 'U-net (With RGBN)' ? 'active' : ''}`}
                >
                  U-net (With RGBN)
                </button>
              </li>
            </ul>
          </div>

          <div className="sidebar-section">
            <h3 className="section-title">Time consuming:</h3>
            <div className="time-consuming-container">
              <div className="time-consuming-info">
                <span className="processing-text">Processing...</span>
                <div className="progress-bar">
                  <div className="progress-fill"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="main-content">
        <h2 className="content-title">{activeTool}</h2>
        <p className="image-count">Displaying the latest {Math.min(receivedImages.length, MAX_IMAGES_TO_DISPLAY)} images (newest first).</p>
        
        <div className="image-gallery">
          {receivedImages.length > 0 ? (
            receivedImages.map((img) => (
              <div key={img.imageId} className="image-card">
                <h2 className="image-title">{img.imageId}</h2>
                <img
                  src={activeTool === 'NDVI' ? img.ndviUrl : img.rgbUrl}
                  alt={img.imageId}
                  className="image"
                  loading="lazy"
                />
                {img.metadata && (
                  <div className="image-metadata">
                    <p>Resolution: {img.metadata.resolution?.join(' x ')}</p>
                    <p>Bands: {img.metadata.bands?.join(', ')}</p>
                  </div>
                )}
              </div>
            ))
          ) : (
            <div className="no-images">
              <p>Waiting for images...</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;