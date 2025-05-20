import React, { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';

const WEBSOCKET_URL = 'ws://localhost:8000/ws'; 
const MAX_IMAGES_TO_DISPLAY = 20; 




function App() {
  const [receivedImages, setReceivedImages] = useState([]);
  const [connectionStatus, setConnectionStatus] = useState('Connecting...');
  const [activeTool, setActiveTool] = useState('NDVI');
  const [uavImages, setUavImages] = useState({});
  const [isLogPanelOpen, setIsLogPanelOpen] = useState(false);
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
          setUavImages((prevImages) => ({
            ...prevImages,
            [message.uav_id]: {
              imageId: `UAV-${message.uav_id}-${message.timestamp}`,
              metadata: message.metadata,
              rgbUrl: message.rgb_url,
              ndviUrl: message.ndvi_url,
              overlayUrl: message.overlay_url,
              timestamp: message.timestamp  
            }
          }));
        }
      } catch (error) {
        console.error('Failed to parse message:', error);
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

  // Add new component for processing logs
  const ProcessingLogs = ({ uavImages }) => {
    return (
      <div className="processing-logs">
        {Object.entries(uavImages).map(([uavId, img]) => {
          const info = img.metadata?.processing_info;
          if (!info) return null;
          
          return (
            <div key={uavId} className="log-entry">
              <br />
              <span className="uav-id">[UAV{uavId}]:</span>
              <span className="time">time: {info.time_seconds}s,</span> <br />
              <br />
              <span className="anomalies">
                Stress found: {info.detected_anomalies.length > 0 
                  ? `{${info.detected_anomalies.join(', ')}}`
                  : 'none'}
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  const LogPanel = ({ isOpen, onClose, uavImages }) => {
    return (
      <div className={`log-panel ${isOpen ? 'open' : ''}`}>
        <div className="log-panel-header">
          <h3>Processing Logs</h3>
          <button className="close-button" onClick={onClose}>×</button>
        </div>
        <div className="log-panel-content">
          {Object.entries(uavImages).map(([uavId, img]) => {
            const info = img.metadata?.processing_info;
            if (!info) return null;
            
            return (
              <div key={uavId} className="log-entry">
                <span className="uav-id">[UAV{uavId}]:</span>
                <span className="time">time: {info.time_seconds}s</span>
                <span className="anomalies">
                  stress_found: {info.detected_anomalies.length > 0 
                    ? `{${info.detected_anomalies.join(', ')}}`
                    : 'none'}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
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
            <h3 className="section-title">Visual type:</h3>
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
                  onClick={() => handleToolSelect('Model Prediction')}
                  className={`tool-button ${activeTool === 'Model Prediction' ? 'active' : ''}`}
                >
                  Model Prediction
                </button>
              </li>
            
            </ul>
          </div>

          <div className="sidebar-section">
            <h3 className="section-title">Stress Types:</h3>
            <div className="stress-colors">
              <div className="stress-color-item">
                <div className="color-box" style={{backgroundColor: 'rgb(255, 0, 0)'}}></div>
                <span>Nutrient Deficiency</span>
              </div>
              <div className="stress-color-item">
                <div className="color-box" style={{backgroundColor: 'rgb(0, 255, 0)'}}></div>
                <span>Drydown</span>
              </div>
              <div className="stress-color-item">
                <div className="color-box" style={{backgroundColor: 'rgb(0, 0, 255)'}}></div>
                <span>Water</span>
              </div>
              <div className="stress-color-item">
                <div className="color-box" style={{backgroundColor: 'rgb(255, 255, 0)'}}></div>
                <span>Weed Cluster</span>
              </div>
              <div className="stress-color-item">
                <div className="color-box" style={{backgroundColor: 'rgb(255, 0, 255)'}}></div>
                <span>Planter Skip</span>
              </div>
            </div>
          </div>

          {/* Update the time consuming section in the sidebar */}
          {/* <div className="sidebar-section">
            <h3 className="section-title">Processing Logs:</h3>
            <div className="time-consuming-container">
              <ProcessingLogs uavImages={uavImages} />
            </div>
          </div> */}
        </div>
      </div>

      {/* Main Content */}
      <div className="main-content">
        <div className="main-header">
          <h2 className="content-title">{activeTool}</h2>
          <button 
            className="log-toggle-button"
            onClick={() => setIsLogPanelOpen(!isLogPanelOpen)}
          >
            {isLogPanelOpen ? 'Hide Logs' : 'Show Logs'}
          </button>
        </div>
        
        <p className="image-count">Displaying latest image from each UAV.</p>
        
        <div className="image-gallery">
          {Object.entries(uavImages).length > 0 ? (
            Object.entries(uavImages)
              .sort(([uavId1], [uavId2]) => uavId1.localeCompare(uavId2))
              .map(([uavId, img]) => (
                <div key={img.imageId} className="image-card">
                  <h2 className="image-title">UAV {uavId}</h2>
                  <img
                    src={
                    activeTool === 'NDVI' 
                      ? img.ndviUrl 
                      : activeTool === 'Model Prediction'
                        ? img.overlayUrl
                        : img.rgbUrl
                  }
                    alt={img.imageId}
                    className="image"
                    loading="lazy"
                  />
                  {img.metadata && (
                    <div className="image-metadata">
                      <p>Resolution: {img.metadata.resolution?.join(' x ')}</p>
                      <p>Bands: {img.metadata.bands?.join(', ')}</p>
                      <p>Last Update: {new Date(img.timestamp * 1000).toLocaleString()}</p>
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

        <LogPanel 
          isOpen={isLogPanelOpen} 
          onClose={() => setIsLogPanelOpen(false)}
          uavImages={uavImages}
        />
      </div>
    </div>
  );
}

export default App;