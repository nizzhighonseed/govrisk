export function formatCurrency(amount: number): string {
  const formatted = amount.toLocaleString('en-IN');
  return `₹${formatted} Cr`;
}

/**
 * Shown when a government source never published a measurement. A real 0 is
 * rendered normally — "not reported" and "zero" are different facts.
 */
export const NO_DATA_LABEL = 'Not reported';

export function formatCurrencyNullable(amount: number | null | undefined): string {
  return amount == null ? NO_DATA_LABEL : formatCurrency(amount);
}

export function formatPercentNullable(value: number | null | undefined): string {
  return value == null ? NO_DATA_LABEL : `${Math.round(value)}%`;
}

export function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

export function getRiskColor(level: string): string {
  switch (level) {
    case 'LOW':
      return 'text-green-600';
    case 'MEDIUM':
      return 'text-yellow-600';
    case 'HIGH':
      return 'text-orange-600';
    case 'CRITICAL':
      return 'text-red-600';
    default:
      return 'text-gray-600';
  }
}

export function getRiskBgColor(level: string): string {
  switch (level) {
    case 'LOW':
      return 'bg-green-100';
    case 'MEDIUM':
      return 'bg-yellow-100';
    case 'HIGH':
      return 'bg-orange-100';
    case 'CRITICAL':
      return 'bg-red-100';
    default:
      return 'bg-gray-100';
  }
}

export function getRiskBorderColor(level: string): string {
  switch (level) {
    case 'LOW':
      return 'border-green-300';
    case 'MEDIUM':
      return 'border-yellow-300';
    case 'HIGH':
      return 'border-orange-300';
    case 'CRITICAL':
      return 'border-red-300';
    default:
      return 'border-gray-300';
  }
}

export function cn(...classes: (string | boolean | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}
