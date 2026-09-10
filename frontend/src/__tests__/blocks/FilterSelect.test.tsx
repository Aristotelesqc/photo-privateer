import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { FilterSelect } from '../../components/blocks/FilterSelect';

describe('FilterSelect Component', () => {
  it('renders styled select dropdown and handles change events', () => {
    const handleChange = vi.fn();
    render(
      <FilterSelect value="opt2" onChange={handleChange} aria-label="Test Filter">
        <option value="opt1">Option 1</option>
        <option value="opt2">Option 2</option>
      </FilterSelect>
    );

    const select = screen.getByRole('combobox', { name: 'Test Filter' });
    expect(select).toBeInTheDocument();
    expect(select).toHaveValue('opt2');

    fireEvent.change(select, { target: { value: 'opt1' } });
    expect(handleChange).toHaveBeenCalledTimes(1);
  });
});
