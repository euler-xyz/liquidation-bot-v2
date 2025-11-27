// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IGsm {
  /**
   * @notice Sells the GSM underlying asset in exchange for buying USDXL
   * @dev Use `getAssetAmountForSellAsset` function to calculate the amount based on the USDXL amount to buy
   * @param maxAmount The maximum amount of the underlying asset to sell
   * @param receiver Recipient address of the USDXL being purchased
   * @return The amount of underlying asset sold
   * @return The amount of USDXL bought by the user
   */
  function sellAsset(uint256 maxAmount, address receiver) external returns (uint256, uint256);

  /**
   * @notice Returns the underlying asset of the GSM
   * @return The address of the underlying asset
   */
  function UNDERLYING_ASSET() external view returns (address);
}