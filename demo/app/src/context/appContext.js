import { createContext, useContext, useMemo, useState } from 'react';
import usePostRequest from 'src/hooks/usePostRequest';
import useGetRequest from '../hooks/useGetRequest';
import { formatToValidTuple, formatToISOString } from 'src/utils';

const AppContext = createContext();

export default function AppProvider({ children }) {
  const today = new Date();
  /**
   * @typedef {object} UserParams
   * @property {[Date, Date]} dateRange
   * @property {number[]} [bbox]
  */
  /** @type {[UserParams, Function]} */
  const [
    userParams,
    setUserParams
  ] = useState({
    dateRange: [
    today,
    new Date(new Date(today).setDate(today.getDate() + 7)),
  ]
  });
  const [hoveredOpportunity, setHoveredOpportunity] = useState(null);
  const [selectedOpportunity, setSelectedOpportunity] = useState(null);
  const [openFilters, setOpenFilters] = useState(false);

  const params = useMemo(() => {
    return userParams.bbox ? {
      "bbox": formatToValidTuple(userParams.bbox),
      "datetime": formatToISOString(userParams.dateRange)
      //start_date: dateRange[0], call time formatting here
      //end_date: dateRange[1] call time formatting here
    } : null;
  }, [userParams])

  const { isLoading: isLoadingOpps, data: opportunities, error: errorOpps } = usePostRequest(params);
  const { isLoading: isLoadingProducts, data: products, error: errorProducts } = useGetRequest();

  console.log(products);
  const app = {
    userParams,
    setUserParams,
    isLoadingOpps,
    isLoadingProducts,
    products,
    errorProducts,
    opportunities,
    errorOpps,
    selectedOpportunity,
    setSelectedOpportunity,
    hoveredOpportunity,
    setHoveredOpportunity,
    openFilters,
    setOpenFilters,
    setHoveredOpportunity
  }

  return (
    <AppContext.Provider value={app}>
      {children}
    </AppContext.Provider>
  )
}

export function useAppContext() {
  return useContext(AppContext);
}
