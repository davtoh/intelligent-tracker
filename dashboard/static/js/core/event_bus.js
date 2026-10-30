/**
 * Intelligent Tracker - Decoupled Pub/Sub Event Bus.
 * Enables zero-coupling inter-module communication across tabs and features.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  class EventBus {
    constructor() {
      this._listeners = new Map();
    }

    /**
     * Subscribe to an event topic.
     * @param {string} event
     * @param {Function} handler
     * @returns {Function} unsubscribe callback
     */
    on(event, handler) {
      if (typeof handler !== 'function') return () => {};
      if (!this._listeners.has(event)) {
        this._listeners.set(event, new Set());
      }
      this._listeners.get(event).add(handler);
      return () => this.off(event, handler);
    }

    /**
     * Unsubscribe from an event topic.
     * @param {string} event
     * @param {Function} handler
     */
    off(event, handler) {
      if (this._listeners.has(event)) {
        this._listeners.get(event).delete(handler);
        if (this._listeners.get(event).size === 0) {
          this._listeners.delete(event);
        }
      }
    }

    /**
     * Emit an event to all registered listeners.
     * @param {string} event
     * @param {*} data
     */
    emit(event, data) {
      if (this._listeners.has(event)) {
        this._listeners.get(event).forEach(handler => {
          try {
            handler(data);
          } catch (err) {
            console.error(`[EventBus] Error in handler for event "${event}":`, err);
          }
        });
      }
    }
  }

  const bus = new EventBus();
  window.TrackerApp.bus = bus;
})();

