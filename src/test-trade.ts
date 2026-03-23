import 'dotenv/config';
import Alpaca from '@alpacahq/alpaca-trade-api';

const alpaca = new Alpaca({
  keyId: process.env.ALPACA_API_KEY_ID!,
  secretKey: process.env.ALPACA_API_SECRET_KEY!,
  paper: true,
});

const SYMBOL = 'AAPL';
const QTY = 1;

function wait(ms: number) {
  return new Promise((res) => setTimeout(res, ms));
}

async function main() {
  console.log('===========================================');
  console.log('   TEST TRADE — Paper Account             ');
  console.log('===========================================\n');

  // 1. Account info
  const acct = await alpaca.getAccount();
  console.log(`Account equity:  $${parseFloat(acct.equity).toFixed(2)}`);
  console.log(`Buying power:    $${parseFloat(acct.buying_power).toFixed(2)}\n`);

  // 1b. Cancel any leftover orders from previous runs
  console.log('Cancelling any existing open orders…');
  await alpaca.cancelAllOrders();
  await wait(3000);
  console.log('✔  Clean slate.\n');

  // 2. Get latest price
  let latestPrice = 200; // fallback
  try {
    const bars = alpaca.getBarsV2(SYMBOL, { timeframe: '1Min', limit: 1, feed: 'iex' });
    for await (const bar of bars) {
      latestPrice = bar.ClosePrice as number;
    }
  } catch {
    console.log('Could not fetch live price, using fallback $200');
  }

  const buyPrice  = parseFloat((latestPrice * 0.999).toFixed(2)); // 0.1% below market
  const sellPrice = parseFloat((latestPrice * 1.001).toFixed(2)); // 0.1% above market

  console.log(`${SYMBOL} last price: $${latestPrice.toFixed(2)}`);
  console.log(`Placing BUY  limit @ $${buyPrice}  for ${QTY} share(s)…`);

  // 3. Place BUY limit order
  const buyOrder = await alpaca.createOrder({
    symbol: SYMBOL,
    qty: QTY,
    side: 'buy',
    type: 'limit',
    time_in_force: 'day',
    limit_price: buyPrice.toFixed(2),
  });
  console.log(`✔  BUY order placed  | ID: ${buyOrder.id} | Status: ${buyOrder.status}\n`);

  await wait(3000);

  // 4. Cancel the buy order first (market is closed — it won't fill)
  console.log('Cancelling BUY order…');
  await alpaca.cancelOrder(buyOrder.id);
  await wait(4000); // wait for Alpaca to process the cancellation
  console.log('✔  BUY order cancelled.\n');

  // 5. Place SELL limit order (now safe — no open long)
  console.log(`Placing SELL limit @ $${sellPrice}  for ${QTY} share(s)…`);
  const sellOrder = await alpaca.createOrder({
    symbol: SYMBOL,
    qty: QTY,
    side: 'sell',
    type: 'limit',
    time_in_force: 'day',
    limit_price: sellPrice.toFixed(2),
  });
  console.log(`✔  SELL order placed | ID: ${sellOrder.id} | Status: ${sellOrder.status}\n`);

  await wait(3000);

  // 6. Cancel the sell order too
  console.log('Cancelling SELL order…');
  await alpaca.cancelAllOrders();
  console.log('✔  All orders cancelled.\n');

  console.log('===========================================');
  console.log('   TEST COMPLETE                          ');
  console.log('===========================================');
}

main().catch((err) => {
  console.error('Test failed:', err?.response?.data ?? err.message ?? err);
  process.exit(1);
});
