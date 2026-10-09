import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App';
import './style.css';
import './fluid.css';
import './kaomoji.css';
import './blanca.css';
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
