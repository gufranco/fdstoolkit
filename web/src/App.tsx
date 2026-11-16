import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactElement, useState } from 'react';

import { Page } from './Page';

export function App(): ReactElement {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return (
    <QueryClientProvider client={client}>
      <Page />
    </QueryClientProvider>
  );
}
