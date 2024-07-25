// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {Liquidator} from "../contracts/Liquidator.sol";

contract LiquidatorTest is Test {
    Liquidator public liquidator;

    address swapperAddress = vm.envAddress("SWAPPER_ADDRESS");
    address swapVerifierAddress = vm.envAddress("SWAP_VERIFIER_ADDRESS");
    address evcAddress = vm.envAddress("EVC_ADDRESS");

    function setUp() public {
        liquidator = new Liquidator(swapperAddress, swapVerifierAddress, evcAddress);
    }

    function test_setup() public {
        assertEq(liquidator.swapperAddress(), swapperAddress);
        assertEq(liquidator.swapVerifierAddress(), swapVerifierAddress);
        assertEq(liquidator.evcAddress(), evcAddress);
    }

    function test_liquidate_fail() public {
        Liquidator.LiquidationParams memory params = Liquidator.LiquidationParams({
            violatorAddress: address(0),
            vault : address(0),
            borrowedAsset : address(0),
            collateralVault : address(0),
            collateralAsset : address(0),
            repayAmount : 0,
            seizedCollateralAmount : 0,
            swapAmount: 0,
            expectedRemainingCollateral : 0,
            swapData : new bytes(0)
        });
        
        vm.expectRevert();
        bool success = liquidator.liquidate_single_collateral(params);
    }
}
