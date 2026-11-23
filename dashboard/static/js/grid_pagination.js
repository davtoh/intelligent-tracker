/**
 * Intelligent Tracker - Multi-Camera Grid Pagination State Module.
 * Pure page-size, clamping, slicing, and localStorage persistence helpers.
 */

(function () {
  'use strict';

  const LAYOUT_PAGE_SIZES = {
    '1x1': 1,
    '2x2': 4,
    '3x3': 9,
    '4x4': 16,
  };

  const STORAGE_KEYS = {
    layout: 'it_grid_layout',
    page: 'it_grid_page',
  };

  function isValidLayout(layout) {
    return Object.prototype.hasOwnProperty.call(LAYOUT_PAGE_SIZES, layout);
  }

  function getPageSize(layout) {
    return isValidLayout(layout) ? LAYOUT_PAGE_SIZES[layout] : 4;
  }

  function getTotalPages(totalItems, layout) {
    const count = Math.max(0, Math.floor(Number(totalItems) || 0));
    const pageSize = getPageSize(layout);
    return Math.max(1, Math.ceil(count / pageSize));
  }

  function clampPage(page, totalItems, layout) {
    const parsed = Math.floor(Number(page) || 1);
    const totalPages = getTotalPages(totalItems, layout);
    return Math.min(Math.max(1, parsed), totalPages);
  }

  function slicePage(items, page, layout) {
    const list = Array.isArray(items) ? items : [];
    const pageSize = getPageSize(layout);
    const totalPages = getTotalPages(list.length, layout);
    const safePage = clampPage(page, list.length, layout);
    const start = (safePage - 1) * pageSize;
    return {
      items: list.slice(start, start + pageSize),
      page: safePage,
      totalPages: totalPages,
      pageSize: pageSize,
      totalItems: list.length,
    };
  }

  function readStorage(key) {
    try {
      return typeof window !== 'undefined' && window.localStorage
        ? window.localStorage.getItem(key)
        : null;
    } catch (_) {
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        window.localStorage.setItem(key, String(value));
      }
    } catch (_) {
      // Ignore storage quota or sandbox errors
    }
  }

  function loadState() {
    const rawLayout = readStorage(STORAGE_KEYS.layout);
    const rawPage = readStorage(STORAGE_KEYS.page);
    const layout = isValidLayout(rawLayout) ? rawLayout : '1x1';
    const parsedPage = Math.floor(Number(rawPage) || 1);
    return {
      layout: layout,
      page: parsedPage >= 1 ? parsedPage : 1,
    };
  }

  function saveState(layout, page) {
    const safeLayout = isValidLayout(layout) ? layout : '1x1';
    const safePage = Math.max(1, Math.floor(Number(page) || 1));
    writeStorage(STORAGE_KEYS.layout, safeLayout);
    writeStorage(STORAGE_KEYS.page, safePage);
    return { layout: safeLayout, page: safePage };
  }

  let currentState = loadState();

  function getState() {
    return { layout: currentState.layout, page: currentState.page };
  }

  function setLayout(layout, totalItems) {
    const safeLayout = isValidLayout(layout) ? layout : '1x1';
    const nextPage = clampPage(currentState.page, totalItems || 0, safeLayout);
    currentState = saveState(safeLayout, nextPage);
    return getState();
  }

  function setPage(page, totalItems, layoutOverride) {
    const layout = isValidLayout(layoutOverride) ? layoutOverride : currentState.layout;
    const nextPage = clampPage(page, totalItems || 0, layout);
    currentState = saveState(layout, nextPage);
    return getState();
  }

  function prevPage(totalItems, layoutOverride) {
    return setPage(currentState.page - 1, totalItems, layoutOverride);
  }

  function nextPage(totalItems, layoutOverride) {
    return setPage(currentState.page + 1, totalItems, layoutOverride);
  }

  function paginate(items, layoutOverride) {
    const layout = isValidLayout(layoutOverride) ? layoutOverride : currentState.layout;
    const result = slicePage(items, currentState.page, layout);
    if (result.page !== currentState.page || layout !== currentState.layout) {
      currentState = saveState(layout, result.page);
    }
    return result;
  }

  window.GridPagination = {
    LAYOUT_PAGE_SIZES: LAYOUT_PAGE_SIZES,
    STORAGE_KEYS: STORAGE_KEYS,
    getPageSize: getPageSize,
    getTotalPages: getTotalPages,
    clampPage: clampPage,
    slicePage: slicePage,
    loadState: loadState,
    saveState: saveState,
    getState: getState,
    setLayout: setLayout,
    setPage: setPage,
    prevPage: prevPage,
    nextPage: nextPage,
    paginate: paginate,
  };
})();
